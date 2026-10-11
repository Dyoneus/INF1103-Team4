import json

#Load ai output from a JSON file
def load_ai_output():
    try:
        with open("ai_output.json", "r") as file:
            return json.load(file)

    except (FileNotFoundError, json.JSONDecodeError):
        return None

# for testing
# ai_output = load_ai_output()
# print("AI output loaded:")
# print(ai_output)