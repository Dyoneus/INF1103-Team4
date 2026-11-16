
class LogicManager:

    def __init__(self):
        # Allowed values from the AI Manager
        self.__allowed_values = {
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

        # Optional fields: only present when photos were sent to the AI
        self.__optional_values = {
            "photo_match": ["MATCHED", "UNMATCHED"]
        }

    # Check whether one AI result is valid
    def validate_ai_output(self, ai_output):
        if not isinstance(ai_output, dict):
            return False

        # Success results include "error": None; only actual failures are invalid.
        if ai_output.get("status") == "error" or ai_output.get("error") is not None:
            return False

        for field, allowed_values in self.__allowed_values.items():
            value = ai_output.get(field)

            if not isinstance(value, str):
                return False

            if value not in allowed_values:
                return False

        for field, allowed_values in self.__optional_values.items():
            if field not in ai_output:
                continue

            if ai_output[field] not in allowed_values:
                return False

        return True

    # Check for incomplete reports
    def check_incomplete(self, ai_output):
        if not self.validate_ai_output(ai_output):
            return False

        if (
            ai_output["issue_clarity"] == "UNCLEAR"
            or ai_output["location_quality"] == "MISSING"
        ):
            return True

        return False

    # Identify reports needing clarification
    def check_needs_clarification(self, ai_output):
        if not self.validate_ai_output(ai_output):
            return False

        if self.check_incomplete(ai_output):
            return False

        if (
            ai_output["location_quality"] == "VAGUE"
            or ai_output["date_quality"] == "MISSING"
            or ai_output["time_quality"] == "MISSING"
            or ai_output.get("photo_match") == "UNMATCHED"
        ):
            return True

        return False

    # Identify reports ready for review
    def check_ready_for_review(self, ai_output):
        if not self.validate_ai_output(ai_output):
            return False

        # Reports with missing or unclear information are not ready
        if self.check_incomplete(ai_output):
            return False

        if self.check_needs_clarification(ai_output):
            return False

        if (
            ai_output["issue_clarity"] == "CLEAR"
            and ai_output["location_quality"] == "ADEQUATE"
            and ai_output["date_quality"] in ["EXACT", "APPROXIMATE"]
            and ai_output["time_quality"] in ["EXACT", "APPROXIMATE"]
            and ai_output.get("photo_match") != "UNMATCHED"
        ):
            return True

        return False

    # Apply rules in the correct order
    def determine_report_status(self, ai_output):

        # Rule 1: AI_FAILED
        if not self.validate_ai_output(ai_output):
            return {
                "status": "AI_FAILED",
                "clarification_codes": []
            }

        clarification_codes = []

        if ai_output["issue_clarity"] == "UNCLEAR":
            clarification_codes.append("CLARIFY_OBSERVATION")

        # The attached photo does not show what the description says
        if ai_output.get("photo_match") == "UNMATCHED":
            clarification_codes.append("CLARIFY_PHOTO")

        if ai_output["location_quality"] == "MISSING":
            clarification_codes.append("ADD_LOCATION")
        elif ai_output["location_quality"] == "VAGUE":
            clarification_codes.append("CLARIFY_LOCATION")

        if ai_output["date_quality"] == "MISSING":
            clarification_codes.append("ADD_DATE")

        if ai_output["time_quality"] == "MISSING":
            clarification_codes.append("ADD_TIME")

        # Rule 2: INCOMPLETE
        if self.check_incomplete(ai_output):
            status = "INCOMPLETE"

        # Rule 3: NEEDS_CLARIFICATION
        elif self.check_needs_clarification(ai_output):
            status = "NEEDS_CLARIFICATION"

        # Rule 4: READY_FOR_REVIEW
        elif self.check_ready_for_review(ai_output):
            status = "READY_FOR_REVIEW"

        # For unexpected combinations
        else:
            status = "AI_FAILED"

        return {
            "status": status,
            "clarification_codes": clarification_codes
        }

    # Sort reports based on workplace location
    def sort_reports_by_location(self, reports):

        if not isinstance(reports, list):
            return []

        location_groups = {}

        for report in reports:

            if not isinstance(report, dict):
                continue

            case_details = report.get("case_details")

            if not isinstance(case_details, dict):
                continue

            location = case_details.get("workplace_location")

            if not isinstance(location, str) or not location.strip():
                continue

            # Standardise spacing and capitalisation
            location = " ".join(location.split())
            location_key = location.casefold()

            if location_key not in location_groups:
                location_groups[location_key] = {
                    "location": location,
                    "reports": []
                }

            group = location_groups[location_key]

            group["reports"].append(report)

        location_summary = []

        for group in location_groups.values():

            location_summary.append({
                "location": group["location"],
                "report_count": len(group["reports"]),
                "reports": group["reports"]
            })

        # Sort by report count, highest first
        location_summary.sort(
            key=lambda item: (
                -item["report_count"],
                item["location"].casefold()
            )
        )

        return location_summary