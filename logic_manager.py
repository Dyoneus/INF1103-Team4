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

    if not isinstance(ai_output.get("reference_id"), str):
        return False

    if not ai_output["reference_id"].strip():
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
        or ai_output["safety_category"] == "UNCLEAR"
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
            "reason": "AI output is invalid or analysis failed."
        }

    # Rule 2: INCOMPLETE
    if check_incomplete(ai_output):
        return {
            "status": "INCOMPLETE",
            "reason": "The safety issue is unclear or the location is missing."
        }

    # Rule 3: NEEDS_CLARIFICATION
    if check_needs_clarification(ai_output):
        return {
            "status": "NEEDS_CLARIFICATION",
            "reason": "The location, date, time or safety category needs clarification."
        }

    # Rule 4: READY_FOR_REVIEW
    if check_ready_for_review(ai_output):
        return {
            "status": "READY_FOR_REVIEW",
            "reason": "The report contains sufficient information for review."
        }

    # For unexpected combinations
    return {
        "status": "AI_FAILED",
        "reason": "AI output could not be classified."
    }

# Return consistent results for all AI outputs
def process_ai_outputs(ai_outputs):

    if not isinstance(ai_outputs, list):
        return []

    processed_reports = []

    for ai_output in ai_outputs:
        result = determine_report_status(ai_output)

        if isinstance(ai_output, dict):
            report = ai_output.copy()
        else:
            report = {}

        # Add status and reason
        report["status"] = result["status"]
        report["reason"] = result["reason"]

        processed_reports.append(report)

    try:
        with open("processed_reports.json", "w", encoding="utf-8") as file:
            json.dump(processed_reports, file, indent=4, ensure_ascii=False)

    except (OSError, TypeError, ValueError):
        print("Failed to save processed_reports.json")

    return processed_reports

# For testing 
# if __name__ == "__main__":
#     ai_outputs = load_ai_output()

#     if ai_outputs is None:
#         print("Failed to load ai_output.json")

#     else:
#         for ai_output in ai_outputs:

#             # Test determine_report_status()
#             result = determine_report_status(ai_output)
#             print("Reference ID:", ai_output.get("reference_id"))
#             print("Status:", result["status"])
#             print("Reason:", result["reason"])

#         # Test process_ai_outputs()
#         processed_reports = process_ai_outputs(ai_outputs)
#         print("Total reports processed:", len(processed_reports))
#         print("save in processed_reports.json.")

#         print()