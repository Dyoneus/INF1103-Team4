import json

#Load ai output from a JSON file
def load_ai_output():
    try:
        with open("ai_output.json", "r") as file:
            return json.load(file)

    except (FileNotFoundError, json.JSONDecodeError):
        return None

# Allowed values from the AI Manager
ALLOWED_VALUES = {
    "issue_clarity": ["CLEAR", "UNCLEAR"],
    "location_quality": ["ADEQUATE", "VAGUE", "MISSING"],
    "date_quality": ["EXACT", "APPROXIMATE", "MISSING"],
    "time_quality": ["EXACT", "APPROXIMATE", "MISSING"],
    "safety_category": [
        "FIRE",
        "ELECTRICAL",
        "SLIP_TRIP_FALL",
        "STRUCTURAL",
        "EQUIPMENT",
        "CHEMICAL",
        "ENVIRONMENTAL",
        "OTHER",
        "UNCLEAR"
    ]
}

# Check whether one AI result is valid
def validate_ai_output(ai_output):
    if not isinstance(ai_output, dict):
        return False

    if "error" in ai_output:
        return False

    for field, allowed_values in ALLOWED_VALUES.items():
        value = ai_output.get(field)

        if not isinstance(value, str):
            return False

        if value not in allowed_values:
            return False

    return True

# Check for incomplete reports
def check_incomplete(ai_output):
    if not validate_ai_output(ai_output):
        return False

    if (
        ai_output["issue_clarity"] == "UNCLEAR"
        or ai_output["location_quality"] == "MISSING"
    ):
        return True

    return False

# Identify reports needing clarification
def check_needs_clarification(ai_output):
    if not validate_ai_output(ai_output):
        return False

    if check_incomplete(ai_output):
        return False

    if (
        ai_output["location_quality"] == "VAGUE"
        or ai_output["date_quality"] == "MISSING"
        or ai_output["time_quality"] == "MISSING"
    ):
        return True

    return False

# Identify reports ready for review
def check_ready_for_review(ai_output):
    if not validate_ai_output(ai_output):
        return False

    # Reports with missing or unclear information are not ready
    if check_incomplete(ai_output):
        return False

    if check_needs_clarification(ai_output):
        return False

    if (
        ai_output["issue_clarity"] == "CLEAR"
        and ai_output["location_quality"] == "ADEQUATE"
        and ai_output["date_quality"] in ["EXACT", "APPROXIMATE"]
        and ai_output["time_quality"] in ["EXACT", "APPROXIMATE"]
    ):
        return True

    return False

# Apply rules in the correct order
def determine_report_status(ai_output):

    # Rule 1: AI_FAILED
    if not validate_ai_output(ai_output):
        return {
            "status": "AI_FAILED",
        }

    # Rule 2: INCOMPLETE
    if check_incomplete(ai_output):
        return {
            "status": "INCOMPLETE",
        }

    # Rule 3: NEEDS_CLARIFICATION
    if check_needs_clarification(ai_output):
        return {
            "status": "NEEDS_CLARIFICATION",
        }

    # Rule 4: READY_FOR_REVIEW
    if check_ready_for_review(ai_output):
        return {
            "status": "READY_FOR_REVIEW",
        }

    # For unexpected combinations
    return {
        "status": "AI_FAILED",
    }

# Return consistent results for all AI outputs
def process_ai_outputs(ai_outputs):

    if not isinstance(ai_outputs, list):
        return []

    processed_reports = []

    for ai_output in ai_outputs:
        result = determine_report_status(ai_output)

        clarification_codes = []

        if isinstance(ai_output, dict) and validate_ai_output(ai_output):

            if ai_output["issue_clarity"] == "UNCLEAR":
                clarification_codes.append("CLARIFY_OBSERVATION")

            if ai_output["location_quality"] == "MISSING":
                clarification_codes.append("ADD_LOCATION")

            if ai_output["location_quality"] == "VAGUE":
                clarification_codes.append("CLARIFY_LOCATION")

            if ai_output["date_quality"] == "MISSING":
                clarification_codes.append("ADD_DATE")

            if ai_output["time_quality"] == "MISSING":
                clarification_codes.append("ADD_TIME")
                

        if result["status"] == "READY_FOR_REVIEW":
            report = {
                "status": result["status"]
            }

        else:
            report = {
                "status": result["status"],
                "clarification_codes": clarification_codes
            }

        processed_reports.append(report)

    return processed_reports

# For testing 
# if __name__ == "__main__":
#     ai_outputs = load_ai_output()

#     if ai_outputs is None:
#         print("Failed to load ai_output.json")

#     else:
#         if isinstance(ai_outputs, dict):
#             ai_outputs = [ai_outputs]

#         processed_reports = process_ai_outputs(ai_outputs)

#         for report in processed_reports:
#             print("Status:", report["status"])

#             if "clarification_codes" in report:
#                 print("Clarification Codes:", report["clarification_codes"])

#             print()  