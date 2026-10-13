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


#For testing 
if __name__ == "__main__":
    ai_outputs = load_ai_output()

    if ai_outputs is None:
        print("Failed to load ai_output.json")

    else:
        for ai_output in ai_outputs:
            print("Reference ID:", ai_output.get("reference_id"))

            if not validate_ai_output(ai_output):
                print("Invalid AI output")

            elif check_incomplete(ai_output):
                print("Status: INCOMPLETE")

            else:
                print("Status: OK")

            print()