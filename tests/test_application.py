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