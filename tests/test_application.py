from unittest.mock import Mock, call

import pytest
import main


def test_constructor_keeps_supplied_managers_without_calling_them():
    managers = [Mock() for _ in range(4)]

    application = main.SafeReportApplication(*managers)

    assert application._io is managers[0]
    assert application._ai is managers[1]
    assert application._logic is managers[2]
    assert application._data is managers[3]
    assert all(manager.mock_calls == [] for manager in managers)


@pytest.mark.parametrize(
    "error_code",
    ["CONFIG_MISSING", "AI_FAILED", "INVALID_SCHEMA"],
)
@pytest.mark.parametrize("save_succeeds", [True, False])
def test_ai_failure_uses_injected_managers(error_code, save_succeeds):
    io = Mock(spec=["display_processing_error"])
    ai = Mock(spec=["make_result"])
    logic = Mock(spec=["determine_report_status"])
    data = Mock(spec=["save_report"])

    ai_result = {
        "reference_id": "TEST-001",
        "status": "error",
        "error": error_code,
    }
    assessment = {
        "status": "AI_FAILED",
        "clarification_codes": [],
    }

    ai.make_result.return_value = ai_result
    logic.determine_report_status.return_value = assessment
    data.save_report.return_value = save_succeeds

    calls = Mock()
    calls.attach_mock(ai, "ai")
    calls.attach_mock(logic, "logic")
    calls.attach_mock(data, "data")
    calls.attach_mock(io, "io")

    application = main.SafeReportApplication(io, ai, logic, data)
    application.handle_ai_failure("TEST-001", error_code)

    expected_error = error_code if save_succeeds else "SAVE_FAILED"
    assert calls.mock_calls == [
        call.ai.make_result("TEST-001", error=error_code),
        call.logic.determine_report_status(ai_result),
        call.data.save_report("TEST-001", ai_result, assessment),
        call.io.display_processing_error(expected_error),
    ]


def test_existing_function_delegates_to_application(monkeypatch):
    application_class = Mock()
    monkeypatch.setattr(
        main, "SafeReportApplication", application_class
    )

    main.handle_ai_failure("TEST-001", "CONFIG_MISSING")

    application_class.assert_called_once_with(
        io_manager=main.io_manager,
        ai_manager=main.ai_manager,
        logic_manager=main.logic_manager,
        data_manager=main.data_manager,
    )
    application_class.return_value.handle_ai_failure.assert_called_once_with(
        "TEST-001", "CONFIG_MISSING"
    )

@pytest.fixture
def assessment_setup():
    io = Mock(spec=main.io_manager.IOManager)
    ai = Mock(spec=main.ai_manager)
    logic = Mock(spec=main.logic_manager)
    data = Mock(spec=main.data_manager)
    application = main.SafeReportApplication(io, ai, logic, data)

    ai.analyze_incident.return_value = {
        "issue_clarity": "CLEAR",
        "location_quality": "ADEQUATE",
        "date_quality": "EXACT",
        "time_quality": "EXACT",
        "safety_category": "ELECTRICAL",
    }
    logic.determine_report_status.return_value = {
        "status": "READY_FOR_REVIEW",
        "clarification_codes": [],
    }
    data.save_report.return_value = True

    report = {
        "reporter": {"name": "Test User"},
        "case_details": {
            "description": "Exposed electrical cable.",
            "photos": ["evidence.jpg"],
            "consent_for_image_use": False,
        },
    }

    return application, io, ai, logic, data, report


@pytest.mark.parametrize("consent", [True, False, None])
def test_assessment_respects_consent_and_saves_result(
    assessment_setup, consent
):
    application, io, ai, logic, data, report = assessment_setup
    report["case_details"]["consent_for_image_use"] = consent

    result = application.assess_report("TEST-001", report)

    expected_photos = ["evidence.jpg"] if consent is True else []

    ai.get_client.assert_called_once_with()
    ai.analyze_incident.assert_called_once_with(
        ai.get_client.return_value,
        {
            "description": "Exposed electrical cable.",
            "consent_for_image_use": consent,
        },
        expected_photos,
    )
    ai.make_result.assert_called_once_with(
        "TEST-001", fields=ai.analyze_incident.return_value
    )
    logic.determine_report_status.assert_called_once_with(
        ai.make_result.return_value
    )

    assert result is logic.determine_report_status.return_value

    data.save_report.assert_called_once_with(
        "TEST-001", ai.make_result.return_value, result
    )
    io.display_assessment_result.assert_called_once_with(result)
    io.display_processing_error.assert_not_called()

    assert report["case_details"]["photos"] == ["evidence.jpg"]


@pytest.mark.parametrize(
    "error_code",
    ["CONFIG_MISSING", "AI_FAILED", "INVALID_SCHEMA"],
)
def test_assessment_routes_failures_to_instance_handler(
    assessment_setup, error_code
):
    application, io, ai, logic, data, report = assessment_setup
    application.handle_ai_failure = Mock()

    if error_code == "CONFIG_MISSING":
        ai.get_client.side_effect = RuntimeError("Missing configuration")
    elif error_code == "AI_FAILED":
        ai.analyze_incident.side_effect = RuntimeError("API failed")
    else:
        logic.determine_report_status.return_value = {
            "status": "AI_FAILED",
            "clarification_codes": [],
        }

    assert application.assess_report("TEST-001", report) is None

    application.handle_ai_failure.assert_called_once_with(
        "TEST-001", error_code
    )
    data.save_report.assert_not_called()
    io.display_assessment_result.assert_not_called()

    if error_code == "CONFIG_MISSING":
        ai.analyze_incident.assert_not_called()


def test_assessment_save_failure_does_not_display_success(
    assessment_setup
):
    application, io, ai, logic, data, report = assessment_setup
    data.save_report.return_value = False

    assert application.assess_report("TEST-001", report) is None

    data.save_report.assert_called_once_with(
        "TEST-001",
        ai.make_result.return_value,
        logic.determine_report_status.return_value,
    )
    io.display_processing_error.assert_called_once_with("SAVE_FAILED")
    io.display_assessment_result.assert_not_called()


def test_existing_assessment_function_delegates(monkeypatch):
    application_class = Mock()
    monkeypatch.setattr(
        main, "SafeReportApplication", application_class
    )
    report = {"case_details": {}}

    result = main.assess_report("TEST-001", report)

    application_class.assert_called_once_with(
        io_manager=main.io_manager,
        ai_manager=main.ai_manager,
        logic_manager=main.logic_manager,
        data_manager=main.data_manager,
    )
    application_class.return_value.assess_report.assert_called_once_with(
        "TEST-001", report
    )

    assert result is application_class.return_value.assess_report.return_value

@pytest.fixture
def clarification_setup(assessment_setup):
    application, io, ai, logic, data, report = assessment_setup
    report["case_details"]["workplace_location"] = "Warehouse"

    assessment = {
        "status": "NEEDS_CLARIFICATION",
        "clarification_codes": ["CLARIFY_LOCATION"],
    }
    io.collect_clarifications.return_value = {
        "workplace_location": "Block A, level 3"
    }
    data.save_clarifications.return_value = True
    application.assess_report = Mock()

    return application, io, data, report, assessment


@pytest.mark.parametrize("assessment_failed", [False, True])
def test_clarification_saves_before_reassessment(
    clarification_setup, assessment_failed
):
    application, io, data, report, assessment = clarification_setup
    changes = io.collect_clarifications.return_value

    def reassess(reference_id, updated_report):
        assert reference_id == "TEST-001"
        assert updated_report is report
        data.save_clarifications.assert_called_once_with(
            "TEST-001", changes
        )
        assert (
            updated_report["case_details"]["workplace_location"]
            == "Block A, level 3"
        )
        if assessment_failed:
            return None
        return {
            "status": "READY_FOR_REVIEW",
            "clarification_codes": [],
        }

    application.assess_report.side_effect = reassess

    application.run_clarification_loop(
        "TEST-001", report, assessment
    )

    io.collect_clarifications.assert_called_once_with(report)
    application.assess_report.assert_called_once_with(
        "TEST-001", report
    )
    assert (
        report["case_details"]["workplace_location"]
        == "Block A, level 3"
    )
    assert report["case_details"]["photos"] == ["evidence.jpg"]
    assert report["reporter"] == {"name": "Test User"}
    io.display_processing_error.assert_not_called()
    io.display_clarification_questions.assert_not_called()


@pytest.mark.parametrize(
    "outcome",
    [None, {}, EOFError(), KeyboardInterrupt()],
)
def test_clarification_cancellation_does_not_save(
    clarification_setup, outcome
):
    application, io, data, report, assessment = clarification_setup

    if isinstance(outcome, BaseException):
        io.collect_clarifications.side_effect = outcome
    else:
        io.collect_clarifications.return_value = outcome

    application.run_clarification_loop(
        "TEST-001", report, assessment
    )

    data.save_clarifications.assert_not_called()
    application.assess_report.assert_not_called()
    assert report["case_details"]["workplace_location"] == "Warehouse"
    io.display_processing_error.assert_not_called()


def test_clarification_save_failure_stops_reassessment(
    clarification_setup
):
    application, io, data, report, assessment = clarification_setup
    data.save_clarifications.return_value = False

    application.run_clarification_loop(
        "TEST-001", report, assessment
    )

    data.save_clarifications.assert_called_once_with(
        "TEST-001", io.collect_clarifications.return_value
    )
    application.assess_report.assert_not_called()
    assert report["case_details"]["workplace_location"] == "Warehouse"
    io.display_processing_error.assert_called_once_with("SAVE_FAILED")


@pytest.mark.parametrize(
    "status, codes",
    [
        ("READY_FOR_REVIEW", ["CLARIFY_LOCATION"]),
        ("AI_FAILED", ["CLARIFY_LOCATION"]),
        ("NEEDS_CLARIFICATION", []),
    ],
)
def test_clarification_skips_records_without_actionable_questions(
    clarification_setup, status, codes
):
    application, io, data, report, assessment = clarification_setup
    assessment.update(status=status, clarification_codes=codes)

    application.run_clarification_loop(
        "TEST-001", report, assessment
    )

    io.collect_clarifications.assert_not_called()
    data.save_clarifications.assert_not_called()
    application.assess_report.assert_not_called()


@pytest.mark.parametrize("ready_on_last_attempt", [False, True])
def test_clarification_displays_only_outstanding_questions_at_limit(
    clarification_setup, ready_on_last_attempt
):
    application, io, data, report, assessment = clarification_setup
    limit = main.MAX_CLARIFICATION_ATTEMPTS
    results = [assessment.copy() for _ in range(limit)]

    if ready_on_last_attempt:
        results[-1] = {
            "status": "READY_FOR_REVIEW",
            "clarification_codes": [],
        }

    application.assess_report.side_effect = results

    application.run_clarification_loop(
        "TEST-001", report, assessment
    )

    assert io.collect_clarifications.call_count == limit
    assert data.save_clarifications.call_count == limit
    assert application.assess_report.call_count == limit

    if ready_on_last_attempt:
        io.display_clarification_questions.assert_not_called()
    else:
        io.display_clarification_questions.assert_called_once_with(
            ["CLARIFY_LOCATION"]
        )


def test_existing_clarification_function_delegates(monkeypatch):
    application_class = Mock()
    monkeypatch.setattr(
        main, "SafeReportApplication", application_class
    )
    report = {"case_details": {}}
    assessment = {
        "status": "NEEDS_CLARIFICATION",
        "clarification_codes": [],
    }

    main.run_clarification_loop("TEST-001", report, assessment)

    application_class.assert_called_once_with(
        io_manager=main.io_manager,
        ai_manager=main.ai_manager,
        logic_manager=main.logic_manager,
        data_manager=main.data_manager,
    )
    application_class.return_value.run_clarification_loop.assert_called_once_with(
        "TEST-001", report, assessment
    )