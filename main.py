from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import re
import os
from datetime import datetime

app = Flask(__name__)
firebase_admin.initialize_app()
db = firestore.client()


def combine_days(days):
    day_order = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    sorted_days = sorted(days, key=day_order.index)
    groups = []
    temp = [sorted_days[0]]
    for i in range(1, len(sorted_days)):
        if day_order.index(sorted_days[i]) == day_order.index(temp[-1]) + 1:
            temp.append(sorted_days[i])
        else:
            groups.append(temp)
            temp = [sorted_days[i]]
    groups.append(temp)
    result = []
    for g in groups:
        result.append(f"{g[0]}–{g[-1]}" if len(g) > 1 else g[0])
    return ", ".join(result)


@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json()
    print("Incoming request JSON:", req)
    if "sessionInfo" not in req or "session" not in req["sessionInfo"]:
        return (
            jsonify(
                {
                    "fulfillment_response": {
                        "messages": [
                            {"text": {"text": ["Invalid request, 'session' missing."]}}
                        ]
                    }
                }
            ),
            400,
        )

    session = req["sessionInfo"]["session"].split("/")[-1]
    params = req.get("sessionInfo", {}).get("parameters", {})
    tag = req.get("fulfillmentInfo", {}).get("tag", "").strip().lower()
    print("Normalized tag value:", tag)
    lang = req.get("languageCode", "en")
    print(lang)

    if tag == "diag_yes":
        print(params.get("testdate", {}))
        diagdate = params.get("testdate", {})
        day = int(diagdate.get("day", 0))
        month = int(diagdate.get("month", 0))
        year = int(diagdate.get("year", 0))
        formatted_date = f"{year}-{month:02d}-{day:02d}"
        print(formatted_date)

        data = {
            "appointment_date": formatted_date,
            "patient_name": params.get("patientname", ""),
            "phone": params.get("patientmobile", ""),
            "Age": params.get("patientage", ""),
            "Test": params.get("diagnostics", ""),
        }
        try:
            db.collection("diagnostics").document(session).set(data)
        except Exception as e:
            print("🔥 Firestore write error:", e)
        # Return a confirmation message after booking
        diagnostic_name = params.get("diagnostics", "diagnostic")
        return jsonify(
            {
                "fulfillment_response": {
                    "messages": [
                        {
                            "text": {
                                "text": [
                                    f"✅ Your {diagnostic_name} appointment has been booked for {formatted_date}. We will contact you soon."
                                ]
                            }
                        }
                    ]
                }
            }
        )

    # ===================== HOME CARE FLOW =====================
    elif tag == "homecare_booking":
        home_date = params.get("hcservicedate", {})
        day = int(home_date.get("day", 0))
        month = int(home_date.get("month", 0))
        year = int(home_date.get("year", 0))
        formatted_home_date = f"{year}-{month:02d}-{day:02d}"

        data = {
            "service_date": formatted_home_date,
            "name": params.get("patientname", ""),
            "phone": params.get("patientmobile", ""),
            "age": params.get("patientage", ""),
            "selected_service": params.get("homecare", ""),
        }
        db.collection("homecare").document(session).set(data)

    elif tag == "get_states":
        try:
            docs = list(
                db.collection("states_hi" if lang == "hi" else "states").stream()
            )

            states = [doc.id for doc in docs]
            if not states:
                if lang == "hi":
                    return fallback("कोई राज्य नहीं मिला।")
                else:
                    return fallback("No states found.")
            chips = {"type": "chips", "options": [{"text": state} for state in states]}
            return jsonify(
                {
                    "fulfillment_response": {
                        "messages": [
                            {
                                "text": {
                                    "text": [
                                        (
                                            "कृपया एक राज्य चुनें:"
                                            if lang == "hi"
                                            else "Please select a state:"
                                        )
                                    ]
                                }
                            },
                            {"payload": {"richContent": [[chips]]}},
                        ]
                    }
                }
            )

        except:
            return fallback("Error fetching states.")

    elif tag == "get_cities":
        user_state = params.get("state", "").strip()
        try:
            docs = list(
                db.collection("states_hi" if lang == "hi" else "states").stream()
            )

            state_map = {doc.id.lower(): doc.id for doc in docs}
            normalized_state = user_state.lower()

            if normalized_state not in state_map:
                chips = {"type": "chips", "options": [{"text": doc.id} for doc in docs]}
                return jsonify(
                    {
                        "fulfillment_response": {
                            "messages": [
                                {
                                    "text": {
                                        "text": [
                                            (
                                                "राज्य अमान्य है, कृपया फिर से चुनें।"
                                                if lang == "hi"
                                                else "Invalid state. Please select again."
                                            )
                                        ]
                                    }
                                },
                                {"payload": {"richContent": [[chips]]}},
                            ]
                        },
                        "targetPage": req.get("pageInfo", {}).get("currentPage", ""),
                    }
                )

            matched_state = state_map[normalized_state]
            cities_ref = (
                db.collection("states_hi" if lang == "hi" else "states")
                .document(matched_state)
                .collection("cities")
                .stream()
            )
            cities = [doc.id for doc in cities_ref]

            if not cities:
                return fallback(
                    "इस राज्य के लिए कोई शहर नहीं मिला।"
                    if lang == "hi"
                    else "No cities found for this state."
                )

            chips = {"type": "chips", "options": [{"text": city} for city in cities]}
            return jsonify(
                {
                    "fulfillment_response": {
                        "messages": [
                            {
                                "text": {
                                    "text": [
                                        (
                                            f"{matched_state} में एक शहर चुनें:"
                                            if lang == "hi"
                                            else f"Select a city in {matched_state}:"
                                        )
                                    ]
                                }
                            },
                            {"payload": {"richContent": [[chips]]}},
                        ]
                    }
                }
            )

        except:
            return fallback("Error fetching cities.")

    elif tag == "get_address":
        state = str(params.get("state", "")).strip()
        city = str(params.get("city", "")).strip()

        if not state or not city:
            return fallback(
                "कृपया राज्य और शहर दोनों चुनें।"
                if lang == "hi"
                else "Please select both state and city."
            )

        try:
            doc_ref = (
                db.collection("states_hi" if lang == "hi" else "states")
                .document(state)
                .collection("cities")
                .document(city)
            )
            doc = doc_ref.get()
            if not doc.exists:
                return fallback(
                    "चुने गए शहर के लिए कोई पता नहीं मिला।"
                    if lang == "hi"
                    else "No address found for the selected city."
                )
            data = doc.to_dict()
            address = data.get(
                "address",
                ("कोई पता उपलब्ध नहीं है।" if lang == "hi" else "No address available."),
            )

            accordion = {
                "type": "accordion",
                "title": f"{city}, {state}",
                "subtitle": (
                    "यहाँ क्लिक करें" if lang == "hi" else "Click here for address"
                ),
                "image": {
                    "src": {
                        "rawUrl": "https://cdn-icons-png.flaticon.com/512/684/684908.png"
                    }
                },
                "text": address,
            }
            return jsonify(
                {
                    "fulfillment_response": {
                        "messages": [{"payload": {"richContent": [[accordion]]}}]
                    }
                }
            )
        except Exception as e:
            print("ERROR:", e)
            return fallback("Error fetching address.")

    elif tag == "get_address_by_city_only":
        city = params.get("city", "").strip()
        if not city:
            return fallback(
                "कृपया शहर का नाम दर्ज करें।"
                if lang == "hi"
                else "Please enter a city name."
            )

        try:
            states_collection = "states_hi" if lang == "hi" else "states"
            states_ref = db.collection(states_collection).stream()

            for state_doc in states_ref:
                city_doc = (
                    db.collection(states_collection)
                    .document(state_doc.id)
                    .collection("cities")
                    .document(city)
                    .get()
                )
                if city_doc.exists:
                    data = city_doc.to_dict()
                    address = data.get(
                        "address",
                        (
                            "कोई पता उपलब्ध नहीं है।"
                            if lang == "hi"
                            else "No address available."
                        ),
                    )
                    accordion = {
                        "type": "accordion",
                        "title": f"{city}, {state_doc.id}",
                        "subtitle": (
                            "यहाँ क्लिक करें" if lang == "hi" else "Click here for address"
                        ),
                        "image": {
                            "src": {
                                "rawUrl": "https://cdn-icons-png.flaticon.com/512/684/684908.png"
                            }
                        },
                        "text": address,
                    }
                    return jsonify(
                        {
                            "fulfillment_response": {
                                "messages": [
                                    {"payload": {"richContent": [[accordion]]}}
                                ]
                            }
                        }
                    )
            return fallback(
                "इस शहर के लिए कोई पता नहीं मिला।"
                if lang == "hi"
                else "No address found for this city."
            )
        except Exception as e:
            print("ERROR:", e)
            return fallback("Error fetching city address.")

    elif tag == "get_specializations":
        city = params.get("city", "").strip()
        if not city:
            return fallback("Please provide a city.")
        try:
            doctors_ref = db.collection("doctors")
            query = doctors_ref.where(filter=FieldFilter("city", "==", city))
            specializations = set()
            for doc in query.stream():
                data = doc.to_dict()
                specializations.add(data.get("specialization", ""))
            chips = {
                "type": "chips",
                "options": [{"text": s} for s in specializations if s],
            }
            return jsonify(
                {
                    "fulfillment_response": {
                        "messages": [
                            {"text": {"text": ["Please select a specialization:"]}},
                            {"payload": {"richContent": [[chips]]}},
                        ]
                    }
                }
            )
        except Exception as e:
            print("Error fetching specializations:", e)
            return fallback("Error fetching specializations.")

    elif tag == "get_doctors_by_city_and_spec":
        city = params.get("city", "").strip()
        specialization = params.get("specialization", "").strip()
        if not city or not specialization:
            return fallback("City or specialization is missing.")

        try:
            query = (
                db.collection("doctors")
                .where(filter=FieldFilter("city", "==", city))
                .where(filter=FieldFilter("specialization", "==", specialization))
            )

            items = []
            for doc in query.stream():
                data = doc.to_dict()
                doctor_id = data.get("DoctorId", "")
                image_url = data.get("image_url", "https://via.placeholder.com/150")
                page_url = data.get("page_url", "")
                name = data.get("name", "Doctor")
                chips_options = [{"text": f"Dr. {name}"}]
                items.append(
                    [
                        {
                            "type": "image",
                            "rawUrl": image_url,
                            "accessibilityText": name,
                        },
                        {
                            "type": "chips",
                            "options": chips_options,
                        },
                        {
                            "type": "button",
                            "icon": {"type": "link"},
                            "text": "View Profile",
                            "link": page_url,
                        },
                    ]
                )
            if not items:
                return fallback("No doctors found.")

            return jsonify(
                {
                    "fulfillment_response": {
                        "messages": [{"payload": {"richContent": items}}]
                    }
                }
            )

        except Exception as e:
            print("Error fetching doctors:", e)
            return fallback("Something went wrong while fetching doctors.")

    elif tag == "get_doctor_details_by_name":
        doc_name = params.get("doctorname", "").replace("Dr. ", "").strip()
        try:
            docs = (
                db.collection("doctors")
                .where(filter=FieldFilter("name", "==", doc_name))
                .stream()
            )
            for doc in docs:
                data = doc.to_dict()
                description = data.get("description", "")
                page_url = data.get("page_url", "")
                image_url = data.get("image_url", "https://via.placeholder.com/150")
                days = data.get("days", [])
                start = data.get("start", "")
                end = data.get("end", "")
                if isinstance(days, list):
                    days_str = combine_days(days) if days else ""
                else:
                    days_str = str(days)

                def format_time(t):
                    try:
                        return datetime.strptime(t, "%H:%M").strftime("%I:%M %p")
                    except Exception:
                        return t

                start_fmt = format_time(start) if start else ""
                end_fmt = format_time(end) if end else ""
                timings_str = (
                    f"{days_str}: {start_fmt} - {end_fmt}"
                    if days_str and start_fmt and end_fmt
                    else "Not available"
                )
                details = f"""👨‍⚕️ **Dr. {data['name']}**\n🩺 Specialization: {data.get('specialization', '')}\n🎓 {data.get('education', '')}\n🎖 Designation: {data.get('designation', '')}\n🏢 City: {data.get('city', '')}\n📝 Description: {description}\n🔗 [Profile]({page_url})\n🕒 Timings: {timings_str}"""
                return jsonify(
                    {
                        "fulfillment_response": {
                            "messages": [{"text": {"text": [details]}}]
                        }
                    }
                )
            return fallback("")
        except Exception as e:
            print("Fetch error:", e)
            return fallback("Error fetching doctor details.")

    elif tag == "book_doctor_appointment":
        date_obj = params.get("consultationdate", {})
        year = int(date_obj.get("year", 0))
        month = int(date_obj.get("month", 0))
        day = int(date_obj.get("day", 0))

        if not (year and month and day):
            return fallback("❌ Invalid date selected.")

        appointment_date = f"{day:02d}-{month:02d}-{year}"
        time_obj = params.get("consultationtime", {})
        hours = int(time_obj.get("hours", 0))
        minutes = int(time_obj.get("minutes", 0))

        if hours == 0 and minutes == 0:
            return fallback("❌ Invalid time selected.")
        from datetime import time, datetime

        appointment_time_obj = time(hour=hours, minute=minutes)
        appointment_time = appointment_time_obj.strftime("%I:%M %p")

        doctor_name_raw = params.get("doctorname", "")
        if doctor_name_raw is None:
            doctor_name_raw = ""
        doctor_name = re.sub(r"^Dr\.?\s*", "", doctor_name_raw).strip()
        branch = params.get("city", "")
        if not branch:
            return fallback("❌ City/Branch is missing.")

        # Check doctor's availability for the selected date
        doctor_docs = (
            db.collection("doctors")
            .where(filter=FieldFilter("name", "==", doctor_name))
            .stream()
        )
        doctor_data = None
        for doc in doctor_docs:
            doctor_data = doc.to_dict()
            break
        if not doctor_data:
            return fallback("❌ Doctor not found.")

        # Get weekday name for selected date
        try:
            selected_date_obj = datetime(year, month, day)
            selected_weekday = selected_date_obj.strftime("%A")
        except Exception as e:
            return fallback("❌ Invalid date format.")

        # Use Firestore fields: days (list), start, end
        available_days = doctor_data.get("days", [])
        start_time = doctor_data.get("start", "")
        end_time = doctor_data.get("end", "")

        # Format available days using combine_days
        def is_day_available(selected_weekday, available_days):
            # Map full weekday to abbreviation
            day_map = {
                "Monday": "Mon",
                "Tuesday": "Tue",
                "Wednesday": "Wed",
                "Thursday": "Thu",
                "Friday": "Fri",
                "Saturday": "Sat",
                "Sunday": "Sun",
            }
            selected_abbr = day_map.get(selected_weekday, selected_weekday)
            if isinstance(available_days, list):
                # List of abbreviations
                return selected_abbr in available_days
            elif isinstance(available_days, str):
                # Range string, e.g., "Mon-Sat"
                days_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                if "-" in available_days:
                    start_day, end_day = available_days.split("-")
                    try:
                        start_idx = days_order.index(start_day)
                        end_idx = days_order.index(end_day)
                        # Handle wrap-around (e.g., Sat-Mon)
                        if start_idx <= end_idx:
                            valid_days = days_order[start_idx : end_idx + 1]
                        else:
                            valid_days = (
                                days_order[start_idx:] + days_order[: end_idx + 1]
                            )
                        return selected_abbr in valid_days
                    except ValueError:
                        return False
                else:
                    return selected_abbr == available_days
            return False

        if isinstance(available_days, list):
            available_days_str = combine_days(available_days) if available_days else ""
        else:
            available_days_str = str(available_days)
        if not is_day_available(selected_weekday, available_days):
            # Clear date and time parameters and prompt for new ones
            return jsonify(
                {
                    "sessionInfo": {
                        "parameters": {
                            "consultationdate": None,
                            "consultationtime": None,
                            "doctorname": doctor_name,
                            "city": branch,
                        }
                    },
                    "fulfillment_response": {
                        "messages": [
                            {
                                "text": {
                                    "text": [
                                        f"❌ Dr. {doctor_name} is not available on {appointment_date} ({selected_weekday}). Available days: {available_days_str}. Please select another date."
                                    ]
                                }
                            }
                        ]
                    },
                    "targetPage": "7-bookcon_flowend",
                }
            )

        # Check if slot is already booked
        existing = (
            db.collection("appointments")
            .where(filter=FieldFilter("doctor_name", "==", doctor_name))
            .where(filter=FieldFilter("preferred_date", "==", appointment_date))
            .where(filter=FieldFilter("preferred_time", "==", appointment_time))
            .stream()
        )
        if any(existing):
            session_params = {
                "retry_due_to_booking": True,
                "retry_date": appointment_date,
                "retry_time": appointment_time,
            }
            return jsonify(
                {
                    "sessionInfo": {"parameters": session_params},
                    "fulfillment_response": {
                        "messages": [
                            {
                                "text": {
                                    "text": [
                                        f"❌ Slot already booked with Dr. {doctor_name} on {appointment_date} at {appointment_time}. Please choose a different date and time."
                                    ]
                                }
                            }
                        ]
                    },
                }
            )
        appointment_data = {
            "patient_name": params.get("patientname", ""),
            "phone": params.get("patientmobile", ""),
            "age": params.get("patientage", ""),
            "gender": params.get("gender", ""),
            "preferred_date": appointment_date,
            "preferred_time": appointment_time,
            "doctor_name": doctor_name,
            "branch": branch,
        }
        db.collection("appointments").add(appointment_data)
        return jsonify(
            {
                "sessionInfo": {
                    "parameters": {
                        "retry_due_to_booking": None,
                        "retry_date": None,
                        "retry_time": None,
                    }
                },
                "fulfillment_response": {
                    "messages": [
                        {
                            "text": {
                                "text": [
                                    f"✅ Appointment booked with Dr. {doctor_name} on {appointment_date} at {appointment_time} at {branch} branch."
                                ]
                            }
                        }
                    ]
                },
            }
        )

    elif tag == "get_doctor_details":
        doctor_name = params.get("doctorname", "").replace("Dr. ", "").strip()
        try:
            docs = (
                db.collection("doctors")
                .where(filter=FieldFilter("name", "==", doctor_name))
                .stream()
            )
            for doc in docs:
                data = doc.to_dict()
                city = data.get("city", "Unknown")
                days = data.get("days", [])
                start = data.get("start", "")
                end = data.get("end", "")
                if isinstance(days, list):
                    days_str = combine_days(days) if days else ""
                else:
                    days_str = str(days)

                def format_time(t):
                    try:
                        return datetime.strptime(t, "%H:%M").strftime("%I:%M %p")
                    except Exception:
                        return t

                start_fmt = format_time(start) if start else ""
                end_fmt = format_time(end) if end else ""
                timings_str = (
                    f"{days_str}: {start_fmt} - {end_fmt}"
                    if days_str and start_fmt and end_fmt
                    else "Not available"
                )
                detail = f"""👨‍⚕️ **Dr. {data['name']}**\n🩺 Specialization: {data.get('specialization', '')}\n🎓 {data.get('education', '')}\n🎖 Designation: {data.get('designation', '')}\n🏢 City: {city}\n🕒 Timings: {timings_str}"""
                return jsonify(
                    {
                        "sessionInfo": {
                            "parameters": {"doctorname": doctor_name, "city": city}
                        },
                        "fulfillment_response": {
                            "messages": [{"text": {"text": [detail]}}]
                        },
                    }
                )
            return fallback("")
        except Exception as e:
            return fallback("Error fetching doctor details.")
    print("⚠️ Unrecognized tag:", tag)
    return fallback("")


def fallback(msg):
    return jsonify({"fulfillment_response": {"messages": [{"text": {"text": [msg]}}]}})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
