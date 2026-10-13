"""Procedural rules for report readiness."""

from constants import ALLOWED_VALUES

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

    if (
        ai_output["issue_clarity"] == "UNCLEAR"
        or ai_output["location_quality"] == "MISSING"
    ):
        status = "INCOMPLETE"
    elif clarification_codes:
        status = "NEEDS_CLARIFICATION"
    else:
        status = "READY_FOR_REVIEW"

    return {
        "status": status,
        "clarification_codes": clarification_codes
    }
