
from pathlib import Path

import pytest
import main


def test_report_needs_clarification(monkeypatch):

    #simulate a report collected by I/O Manager
    report = {
        "case_details": {
            "description": "Sparks coming from an exposed cable.",
            "workplace_location": "A warehouse in Hougang",
            "incident_datetime": "2026-10-13T15:00",
            "photos": [],
            "consent_for_image_use": False
        },
        "reporter": {"name": "Test User"}
    }

    #simulate a valid Groq response
    ai_fields = {
        "issue_clarity": "CLEAR",
        "location_quality": "VAGUE",
        "date_quality": "EXACT",
        "time_quality": "EXACT",
        "safety_category": "ELECTRICAL"
    }

    saved = {}
    displayed = {}

    #replace user input and raw saving
    monkeypatch.setattr(
        main.io_manager, "collect_report", lambda: report
    )

    monkeypatch.setattr(
        main.data_manager, "create_report",
        lambda report: Path("reports/TEST-001.json")
    )

    #prevent a real Groq API call
    monkeypatch.setattr(
        main.ai_manager, "get_client", lambda: object()
    )

    def fake_analyze(client, incident_data, photo_paths):
        assert "reporter" not in incident_data
        assert photo_paths == []
        return ai_fields

    monkeypatch.setattr(
        main.ai_manager, "analyze_incident", fake_analyze
    )

    #capture what Data Manager would save
    def fake_save(reference_id, ai_result, assessment):
        saved["reference_id"] = reference_id
        saved["ai_result"] = ai_result
        saved["assessment"] = assessment
        return True

    monkeypatch.setattr(
        main.data_manager, "save_report", fake_save
    )

    #prevent terminal output and capture results
    monkeypatch.setattr(
        main.io_manager, "display_report_reference",
        lambda reference_id: None
    )

    monkeypatch.setattr(
        main.io_manager, "display_assessment_result",
        lambda assessment: displayed.update(
            {"assessment": assessment}
        )
    )

    monkeypatch.setattr(
        main.io_manager, "display_clarification_questions",
        lambda codes: displayed.update({"codes": codes})
    )

    #run the workflow
    main.process_new_report()

    #verify the expected result
    assert saved["reference_id"] == "TEST-001"

    assert (
        saved["assessment"]["status"]
        == "NEEDS_CLARIFICATION"
    )

    assert (
        saved["assessment"]["clarification_codes"]
        == ["CLARIFY_LOCATION"]
    )

    assert displayed["codes"] == ["CLARIFY_LOCATION"]



@pytest.mark.parametrize(
    "issue_clarity, location_quality, expected_status, expected_codes",
    [
        ("CLEAR", "ADEQUATE", "READY_FOR_REVIEW", []),
        (
            "UNCLEAR",
            "MISSING",
            "INCOMPLETE",
            ["CLARIFY_OBSERVATION", "ADD_LOCATION"]
        )
    ]
)
def test_other_readiness_statuses(
    monkeypatch,
    issue_clarity,
    location_quality,
    expected_status,
    expected_codes
):
    report = {
        "case_details": {
            "description": "Test safety observation.",
            "photos": [],
            "consent_for_image_use": False
        }
    }

    ai_fields = {
        "issue_clarity": issue_clarity,
        "location_quality": location_quality,
        "date_quality": "EXACT",
        "time_quality": "EXACT",
        "safety_category": "ELECTRICAL"
    }

    saved = {}
    displayed = {}

    # Simulate I/O Manager
    monkeypatch.setattr(
        main.io_manager, "collect_report", lambda: report
    )

    monkeypatch.setattr(
        main.io_manager, "display_report_reference",
        lambda reference_id: None
    )

    monkeypatch.setattr(
        main.io_manager, "display_assessment_result",
        lambda assessment: displayed.update(
            {"assessment": assessment}
        )
    )

    monkeypatch.setattr(
        main.io_manager, "display_clarification_questions",
        lambda codes: displayed.update({"codes": codes})
    )

    # Simulate original report saving
    monkeypatch.setattr(
        main.data_manager, "create_report",
        lambda report: Path("reports/TEST-002.json")
    )

    # Simulate AI without calling Groq
    monkeypatch.setattr(
        main.ai_manager, "get_client", lambda: object()
    )

    monkeypatch.setattr(
        main.ai_manager, "analyze_incident",
        lambda client, incident_data, photo_paths: ai_fields
    )

    # Capture Data Manager's result
    def fake_save(reference_id, ai_result, assessment):
        saved["reference_id"] = reference_id
        saved["assessment"] = assessment
        return True

    monkeypatch.setattr(
        main.data_manager, "save_report", fake_save
    )

    # Run the actual integration workflow
    main.process_new_report()

    # Verify results
    assert saved["reference_id"] == "TEST-002"
    assert saved["assessment"]["status"] == expected_status

    assert (
        saved["assessment"]["clarification_codes"]
        == expected_codes
    )

    assert displayed["assessment"]["status"] == expected_status
    assert displayed["codes"] == expected_codes


def test_save_failure(monkeypatch):
    # Simulate a report
    report = {
        "case_details": {
            "description": "Sparks from an electrical cable.",
            "photos": [],
            "consent_for_image_use": False
        }
    }

    # Simulate a valid AI response
    ai_fields = {
        "issue_clarity": "CLEAR",
        "location_quality": "ADEQUATE",
        "date_quality": "EXACT",
        "time_quality": "EXACT",
        "safety_category": "ELECTRICAL"
    }

    # Collect messages sent to I/O Manager
    messages = []

    monkeypatch.setattr(
        main.io_manager, "collect_report",
        lambda: report
    )

    monkeypatch.setattr(
        main.data_manager, "create_report",
        lambda report: Path("reports/TEST-003.json")
    )

    monkeypatch.setattr(
        main.io_manager, "display_report_reference",
        lambda reference_id: None
    )

    # Simulate AI processing
    monkeypatch.setattr(
        main.ai_manager, "get_client",
        lambda: object()
    )

    monkeypatch.setattr(
        main.ai_manager, "analyze_incident",
        lambda client, incident_data, photo_paths: ai_fields
    )

    # Simulate Data Manager failing to save
    monkeypatch.setattr(
        main.data_manager, "save_report",
        lambda reference_id, ai_result, assessment: False
    )

    # Capture error messages
    monkeypatch.setattr(
        main.io_manager, "display_processing_error",
        lambda code: messages.append(("error", code))
    )

    # Capture unexpected success displays
    monkeypatch.setattr(
        main.io_manager, "display_assessment_result",
        lambda assessment: messages.append(("assessment", assessment))
    )

    monkeypatch.setattr(
        main.io_manager, "display_clarification_questions",
        lambda codes: messages.append(("questions", codes))
    )

    # Run the workflow
    main.process_new_report()

    # Only the save-failure error should be displayed
    assert messages == [("error", "SAVE_FAILED")]


def test_raw_report_save_failure(monkeypatch):
    report = {
        "case_details": {
            "description": "Test safety observation.",
            "photos": [],
            "consent_for_image_use": False
        }
    }

    errors = []

    # Simulate user input
    monkeypatch.setattr(
        main.io_manager, "collect_report",
        lambda: report
    )

    # Simulate a file-saving error
    def fake_create_report(report):
        raise OSError("Simulated file save failure")

    monkeypatch.setattr(
        main.data_manager, "create_report",
        fake_create_report
    )

    # Capture the error code
    monkeypatch.setattr(
        main.io_manager, "display_processing_error",
        lambda code: errors.append(code)
    )

    # AI should not run when saving the raw report fails
    def unexpected_ai_call():
        raise AssertionError("AI should not be called")

    monkeypatch.setattr(
        main.ai_manager, "get_client",
        unexpected_ai_call
    )

    # Run the workflow
    main.process_new_report()

    # Verify the correct error was displayed
    assert errors == ["SAVE_FAILED"]
