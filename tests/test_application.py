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