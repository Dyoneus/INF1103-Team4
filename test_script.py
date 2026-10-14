
"""Test script to demonstrate SafeReport's business rules."""
#you can try to run this test script by running: python -m pytest test_script.py -v

from logic_manager import determine_report_status


# sample structured output from AI Manager
def sample_ai_output():
    return {
        "issue_clarity": "CLEAR",
        "location_quality": "ADEQUATE",
        "date_quality": "EXACT",
        "time_quality": "EXACT",
        "safety_category": "ELECTRICAL"
    }


# rule 1: All required information is clear and present
def test_ready_for_review():
    ai_output = sample_ai_output()

    result = determine_report_status(ai_output)

    assert result["status"] == "READY_FOR_REVIEW"
    assert result["clarification_codes"] == []


# rule 2: Approximate date and time are acceptable
def test_approximate_date_and_time():
    ai_output = sample_ai_output()
    ai_output["date_quality"] = "APPROXIMATE"
    ai_output["time_quality"] = "APPROXIMATE"

    result = determine_report_status(ai_output)

    assert result["status"] == "READY_FOR_REVIEW"


# rule 3: Unclear safety observation
def test_unclear_safety_observation():
    ai_output = sample_ai_output()
    ai_output["issue_clarity"] = "UNCLEAR"

    result = determine_report_status(ai_output)

    assert result["status"] == "INCOMPLETE"
    assert result["clarification_codes"] == ["CLARIFY_OBSERVATION"]


# rule 4: Location is completely missing
def test_missing_location():
    ai_output = sample_ai_output()
    ai_output["location_quality"] = "MISSING"

    result = determine_report_status(ai_output)

    assert result["status"] == "INCOMPLETE"
    assert result["clarification_codes"] == ["ADD_LOCATION"]


# rule 5: Location is provided but too vague
def test_vague_location():
    ai_output = sample_ai_output()
    ai_output["location_quality"] = "VAGUE"

    result = determine_report_status(ai_output)

    assert result["status"] == "NEEDS_CLARIFICATION"
    assert result["clarification_codes"] == ["CLARIFY_LOCATION"]


# rule 6: Date information is missing
def test_missing_date():
    ai_output = sample_ai_output()
    ai_output["date_quality"] = "MISSING"

    result = determine_report_status(ai_output)

    assert result["status"] == "NEEDS_CLARIFICATION"
    assert result["clarification_codes"] == ["ADD_DATE"]


# rule 7: Time information is missing
def test_missing_time():
    ai_output = sample_ai_output()
    ai_output["time_quality"] = "MISSING"

    result = determine_report_status(ai_output)

    assert result["status"] == "NEEDS_CLARIFICATION"
    assert result["clarification_codes"] == ["ADD_TIME"]


# rule 8: Multiple missing fields
# INCOMPLETE takes priority over NEEDS_CLARIFICATION
def test_multiple_missing_fields():
    ai_output = sample_ai_output()
    ai_output["issue_clarity"] = "UNCLEAR"
    ai_output["location_quality"] = "MISSING"
    ai_output["time_quality"] = "MISSING"

    result = determine_report_status(ai_output)

    assert result["status"] == "INCOMPLETE"
    assert result["clarification_codes"] == [
        "CLARIFY_OBSERVATION",
        "ADD_LOCATION",
        "ADD_TIME"
    ]
