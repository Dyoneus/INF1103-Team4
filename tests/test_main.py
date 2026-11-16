
from pathlib import Path
from unittest.mock import Mock

import pytest
import main

@pytest.fixture
def application():
    io = Mock(spec=main.io_manager.IOManager)
    io.review_report_before_submission.side_effect = lambda report: report
    data = Mock(spec=main.data_manager.DataManager)

    return main.SafeReportApplication(
        io,
        main.ai_manager.AIManager(),
        main.logic_manager.LogicManager(),
        data,
    )

def test_report_needs_clarification(monkeypatch, application):

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
        application._io, "collect_report", lambda: report
    )

    monkeypatch.setattr(
        application._data, "create_report",
        lambda report: Path("reports/TEST-001.json")
    )

    #prevent a real Groq API call
    monkeypatch.setattr(
        main.ai_manager.AIManager, "ensure_ready", lambda self: None
    )

    def fake_analyze(self, incident_data, photo_paths):
        assert "reporter" not in incident_data
        assert photo_paths == []
        return ai_fields

    monkeypatch.setattr(
        main.ai_manager.AIManager, "analyze_incident", fake_analyze
    )

    #capture what Data Manager would save
    def fake_save(reference_id, ai_result, assessment):
        saved["reference_id"] = reference_id
        saved["ai_result"] = ai_result
        saved["assessment"] = assessment
        return True

    monkeypatch.setattr(
        application._data, "save_report", fake_save
    )

    #prevent terminal output and capture results
    monkeypatch.setattr(
        application._io, "display_report_reference",
        lambda reference_id: None
    )

    monkeypatch.setattr(
        application._io, "display_assessment_result",
        lambda assessment: displayed.update(
            {"assessment": assessment}
        )
    )

    monkeypatch.setattr(
        application._io, "display_clarification_questions",
        lambda codes: displayed.update({"codes": codes})
    )

    def fake_collect_clarifications(report_data):
        displayed["codes"] = report_data["assessment"]["clarification_codes"]
        return None

    monkeypatch.setattr(
        application._io,
        "collect_clarifications",
        fake_collect_clarifications
    )

    #run the workflow
    application.process_new_report()

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
    application,
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
        application._io, "collect_report", lambda: report
    )

    monkeypatch.setattr(
        application._io,
        "review_report_before_submission",
        lambda report: report
    )

    monkeypatch.setattr(
        application._io, "display_report_reference",
        lambda reference_id: None
    )

    monkeypatch.setattr(
        application._io, "display_assessment_result",
        lambda assessment: displayed.update(
            {"assessment": assessment}
        )
    )

    monkeypatch.setattr(
        application._io, "display_clarification_questions",
        lambda codes: displayed.update({"codes": codes})
    )
    def fake_collect_clarifications(report_data):
        displayed["codes"] = report_data["assessment"]["clarification_codes"]
        return None

    monkeypatch.setattr(
        application._io,
        "collect_clarifications",
        fake_collect_clarifications
    )

    # Simulate original report saving
    monkeypatch.setattr(
        application._data, "create_report",
        lambda report: Path("reports/TEST-002.json")
    )

    # Simulate AI without calling Groq
    monkeypatch.setattr(
        main.ai_manager.AIManager, "ensure_ready", lambda self: None
    )

    monkeypatch.setattr(
        main.ai_manager.AIManager, "analyze_incident",
        lambda self, incident_data, photo_paths: ai_fields
    )

    # Capture Data Manager's result
    def fake_save(reference_id, ai_result, assessment):
        saved["reference_id"] = reference_id
        saved["assessment"] = assessment
        return True

    monkeypatch.setattr(
        application._data, "save_report", fake_save
    )

    # Run the actual integration workflow
    application.process_new_report()

    # Verify results
    assert saved["reference_id"] == "TEST-002"
    assert saved["assessment"]["status"] == expected_status

    assert (
        saved["assessment"]["clarification_codes"]
        == expected_codes
    )

    assert displayed["assessment"]["status"] == expected_status
    if expected_codes:
        assert displayed["codes"] == expected_codes
    else:
        assert "codes" not in displayed


def test_clarification_loop_reassesses_report(monkeypatch, application):
    report = {
        "reference_id": "TEST-CASE",
        "case_details": {
            "description": "Sparks from an electrical cable.",
            "workplace_location": "Warehouse",
            "incident_datetime": "2026-10-13T15:00",
            "photos": [],
            "consent_for_image_use": False,
        },
    }

    first_ai_fields = {
        "issue_clarity": "CLEAR",
        "location_quality": "VAGUE",
        "date_quality": "EXACT",
        "time_quality": "EXACT",
        "safety_category": "ELECTRICAL",
    }
    second_ai_fields = {
        "issue_clarity": "CLEAR",
        "location_quality": "ADEQUATE",
        "date_quality": "EXACT",
        "time_quality": "EXACT",
        "safety_category": "ELECTRICAL",
    }

    ai_calls = {"count": 0}

    def fake_analyze(self, incident_data, photo_paths):
        ai_calls["count"] += 1
        return first_ai_fields if ai_calls["count"] == 1 else second_ai_fields

    monkeypatch.setattr(main.ai_manager.AIManager, "ensure_ready", lambda self: None)
    monkeypatch.setattr(main.ai_manager.AIManager, "analyze_incident", fake_analyze)
    monkeypatch.setattr(application._data, "save_report", lambda *args: True)
    monkeypatch.setattr(application._data, "save_clarifications", lambda *args: True)
    monkeypatch.setattr(application._io, "display_assessment_result", lambda assessment: None)

    collected = {}

    def fake_collect_clarifications(report_data):
        collected["codes"] = report_data["assessment"]["clarification_codes"]
        return {"workplace_location": "Block 30, level 3"}

    monkeypatch.setattr(application._io, "collect_clarifications", fake_collect_clarifications)

    assessment = application.assess_report("TEST-CASE", report)

    assert assessment["status"] == "NEEDS_CLARIFICATION"

    application.run_clarification_loop(
        "TEST-CASE",
        report,
        assessment
    )

    assert collected["codes"] == ["CLARIFY_LOCATION"]
    assert report["case_details"]["workplace_location"] == "Block 30, level 3"
    assert ai_calls["count"] == 2


def test_save_failure(monkeypatch, application):
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
        application._io, "collect_report",
        lambda: report
    )

    monkeypatch.setattr(
        application._data, "create_report",
        lambda report: Path("reports/TEST-003.json")
    )

    monkeypatch.setattr(
        application._io, "display_report_reference",
        lambda reference_id: None
    )

    # Simulate AI processing
    monkeypatch.setattr(
        main.ai_manager.AIManager, "ensure_ready",
        lambda self: None
    )

    monkeypatch.setattr(
        main.ai_manager.AIManager, "analyze_incident",
        lambda self, incident_data, photo_paths: ai_fields
    )

    # Simulate Data Manager failing to save
    monkeypatch.setattr(
        application._data, "save_report",
        lambda reference_id, ai_result, assessment: False
    )

    # Capture error messages
    monkeypatch.setattr(
        application._io, "display_processing_error",
        lambda code: messages.append(("error", code))
    )

    # Capture unexpected success displays
    monkeypatch.setattr(
        application._io, "display_assessment_result",
        lambda assessment: messages.append(("assessment", assessment))
    )

    monkeypatch.setattr(
        application._io, "display_clarification_questions",
        lambda codes: messages.append(("questions", codes))
    )

    # run the workflow
    application.process_new_report()

    # only the save-failure error should be displayed
    assert messages == [("error", "SAVE_FAILED")]


def test_raw_report_save_failure(monkeypatch, application):
    report = {
        "case_details": {
            "description": "Test safety observation.",
            "photos": [],
            "consent_for_image_use": False
        }
    }

    errors = []

    # simulate user input
    monkeypatch.setattr(
        application._io, "collect_report",
        lambda: report
    )

    # simulate a file-saving error
    def fake_create_report(report):
        raise OSError("Simulated file save failure")

    monkeypatch.setattr(
        application._data, "create_report",
        fake_create_report
    )

    # capture the error code
    monkeypatch.setattr(
        application._io, "display_processing_error",
        lambda code: errors.append(code)
    )

    # ai should not run when saving the raw report fails
    def unexpected_ai_call(self):
        raise AssertionError("AI should not be called")

    monkeypatch.setattr(
        main.ai_manager.AIManager, "ensure_ready",
        unexpected_ai_call
    )

    # run the workflow
    application.process_new_report()

    # verify the correct error was displayed
    assert errors == ["SAVE_FAILED"]


def test_clarification_stops_at_attempt_limit(monkeypatch, application):
    report = {
        "reference_id": "TEST-001",
        "case_details": {
            "description": "An unclear safety observation.",
            "workplace_location": "A construction site"
        }
    }

    assessment = {
        "status": "NEEDS_CLARIFICATION",
        "clarification_codes": ["CLARIFY_LOCATION"]
    }

    reassessment_calls = []
    saved_updates = []

    # simulate the user providing a correction each time
    monkeypatch.setattr(
        application._io,
        "collect_clarifications",
        lambda report: {"workplace_location": "Block A"}
    )

    # simulate Data Manager saving corrections
    def fake_save(reference_id, changes):
        saved_updates.append(reference_id)
        return True

    monkeypatch.setattr(
        application._data,
        "save_clarifications",
        fake_save
    )

    # simulate AI always requiring clarification
    def fake_assess(self, reference_id, report):
        reassessment_calls.append(reference_id)
        return assessment.copy()

    monkeypatch.setattr(
        main.SafeReportApplication,
        "assess_report",
        fake_assess
    )

    monkeypatch.setattr(
        application._io,
        "display_clarification_questions",
        lambda codes: None
    )

    application.run_clarification_loop(
        "TEST-001", report, assessment
    )

    # exactly X reassessments, never more
    expected_calls = ["TEST-001"] * main.MAX_CLARIFICATION_ATTEMPTS

    assert reassessment_calls == expected_calls
    assert saved_updates == expected_calls
