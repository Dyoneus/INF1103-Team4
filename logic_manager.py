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

    # Success results include "error": None; only actual failures are invalid.
    if ai_output.get("status") == "error" or ai_output.get("error") is not None:
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
            "clarification_codes": []
        }

    clarification_codes = []

    if ai_output["issue_clarity"] == "UNCLEAR":
        clarification_codes.append("CLARIFY_OBSERVATION")

    if ai_output["location_quality"] == "MISSING":
        clarification_codes.append("ADD_LOCATION")
    elif ai_output["location_quality"] == "VAGUE":
        clarification_codes.append("CLARIFY_LOCATION")

    if ai_output["date_quality"] == "MISSING":
        clarification_codes.append("ADD_DATE")

    if ai_output["time_quality"] == "MISSING":
        clarification_codes.append("ADD_TIME")

    # Rule 2: INCOMPLETE
    if check_incomplete(ai_output):
        status = "INCOMPLETE"

    # Rule 3: NEEDS_CLARIFICATION
    elif check_needs_clarification(ai_output):
        status = "NEEDS_CLARIFICATION"

    # Rule 4: READY_FOR_REVIEW
    elif check_ready_for_review(ai_output):
        status = "READY_FOR_REVIEW"

    # For unexpected combinations
    else:
        status = "AI_FAILED"

    return {
        "status": status,
        "clarification_codes": clarification_codes
    }

# Return consistent results for all AI outputs
def process_ai_outputs(ai_outputs):

    if not isinstance(ai_outputs, list):
        return []

    processed_reports = []

    for ai_output in ai_outputs:
        result = determine_report_status(ai_output)
        processed_reports.append(result)

    return processed_reports