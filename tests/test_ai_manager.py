import json
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_manager
import groq
import httpx
import logic_manager


VALID_FIELDS = {
    "issue_clarity": "CLEAR",
    "location_quality": "ADEQUATE",
    "date_quality": "EXACT",
    "time_quality": "EXACT",
    "safety_category": "FIRE",
}


def assert_raises(expected_exception, function, *args, message=None):
    try:
        function(*args)
    except expected_exception as exc:
        if message is not None:
            assert message in str(exc), (
                f"Expected {message!r} in exception {str(exc)!r}"
            )
        return exc

    raise AssertionError(
        f"Expected {expected_exception.__name__} to be raised"
    )


def test_validate_response_returns_only_normalized_fields():
    response = {**VALID_FIELDS, "issue_clarity": " clear "}

    assert ai_manager.validate_response(json.dumps(response)) == VALID_FIELDS


def test_validate_response_rejects_invalid_output():
    invalid_responses = [
        ["not", "an", "object"],
        {**VALID_FIELDS, "unexpected": "value"},
        {
            key: value
            for key, value in VALID_FIELDS.items()
            if key != "date_quality"
        },
        {**VALID_FIELDS, "safety_category": "UNKNOWN"},
        {**VALID_FIELDS, "issue_clarity": None},
    ]

    for response in invalid_responses:
        assert_raises(
            ValueError,
            ai_manager.validate_response,
            json.dumps(response),
        )


def test_validate_response_rejects_non_string_input():
    assert_raises(
        ValueError,
        ai_manager.validate_response,
        None,
        message="must be a string",
    )


def test_success_result_is_accepted_by_logic_manager():
    result = ai_manager.make_result("report-1", fields=VALID_FIELDS)

    assert result["status"] == "success"
    assert logic_manager.validate_ai_output(result)
    assert logic_manager.determine_report_status(result) == {
        "status": "READY_FOR_REVIEW",
        "clarification_codes": [],
    }


def test_error_result_is_rejected_by_logic_manager():
    result = ai_manager.make_result(
        "report-1",
        error=RuntimeError("offline"),
    )

    assert result["status"] == "error"
    assert not logic_manager.validate_ai_output(result)
    assert logic_manager.determine_report_status(result)["status"] == "AI_FAILED"


def test_process_report_returns_consistent_result_if_client_setup_fails():
    with tempfile.TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "report-1.json"
        report_path.write_text(
            json.dumps(
                {
                    "reference_id": "report-1",
                    "case_details": {},
                }
            ),
            encoding="utf-8",
        )

        result = ai_manager.process_report(
            None,
            report_path,
            Path(temp_dir),
            RuntimeError("API key is missing"),
        )

    assert result == ai_manager.make_result(
        "report-1",
        error=RuntimeError("API key is missing"),
    )


def test_ai_output_path_can_be_configured_for_persistent_storage():
    project_dir = Path("project")

    with patch.dict(
        ai_manager.os.environ,
        {"AI_OUTPUT_PATH": "/data/ai_output.json"},
    ):
        output_path = ai_manager.get_output_path(project_dir)

    assert output_path == Path("/data/ai_output.json")


def test_ai_output_path_defaults_to_project_directory():
    with patch.dict(ai_manager.os.environ):
        ai_manager.os.environ.pop("AI_OUTPUT_PATH", None)
        output_path = ai_manager.get_output_path(Path("project"))

    assert output_path == Path("project") / "ai_output.json"


def test_analyze_incident_stops_after_max_attempts():
    calls = {"count": 0}

    def create(**kwargs):
        calls["count"] += 1
        message = SimpleNamespace(content='{"invalid": true}')
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        )
    )

    with patch.object(ai_manager.time, "sleep"):
        assert_raises(
            RuntimeError,
            ai_manager.analyze_incident,
            client,
            {},
            message="failed after",
        )

    assert calls["count"] == ai_manager.MAX_ATTEMPTS


def test_analyze_incident_retries_connection_failure():
    calls = {"count": 0}

    def create(**kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise groq.APIConnectionError(
                message="connection interrupted",
                request=httpx.Request(
                    "POST",
                    "https://api.groq.com/openai/v1/chat/completions",
                ),
            )

        message = SimpleNamespace(content=json.dumps(VALID_FIELDS))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        )
    )

    with patch.object(ai_manager.time, "sleep"):
        result = ai_manager.analyze_incident(client, {})

    assert result == VALID_FIELDS
    assert calls["count"] == 3


def test_analyze_incident_does_not_retry_non_retryable_api_error():
    calls = {"count": 0}

    def create(**kwargs):
        calls["count"] += 1
        request = httpx.Request(
            "POST",
            "https://api.groq.com/openai/v1/chat/completions",
        )
        response = httpx.Response(401, request=request)
        raise groq.APIStatusError(
            "authentication failed",
            response=response,
            body=None,
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        )
    )

    assert_raises(
        RuntimeError,
        ai_manager.analyze_incident,
        client,
        {},
        message="HTTP 401",
    )
    assert calls["count"] == 1


def run_tests():
    tests = [
        (name, function)
        for name, function in globals().items()
        if name.startswith("test_") and callable(function)
    ]
    failures = 0

    for name, function in tests:
        try:
            function()
        except Exception:
            failures += 1
            print(f"FAIL: {name}")
            traceback.print_exc()
        else:
            print(f"PASS: {name}")

    print(f"\nRan {len(tests)} tests: {len(tests) - failures} passed, {failures} failed")
    return failures


if __name__ == "__main__":
    raise SystemExit(run_tests())
