import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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


class AIManagerTests(unittest.TestCase):
    def test_validate_response_returns_only_normalized_fields(self):
        response = {**VALID_FIELDS, "issue_clarity": " clear "}

        self.assertEqual(
            ai_manager.validate_response(json.dumps(response)),
            VALID_FIELDS,
        )

    def test_validate_response_rejects_invalid_output(self):
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
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    ai_manager.validate_response(json.dumps(response))

    def test_validate_response_rejects_non_string_input(self):
        with self.assertRaisesRegex(ValueError, "must be a string"):
            ai_manager.validate_response(None)

    def test_success_result_is_accepted_by_logic_manager(self):
        result = ai_manager.make_result("report-1", fields=VALID_FIELDS)

        self.assertEqual(result["status"], "success")
        self.assertTrue(logic_manager.validate_ai_output(result))
        self.assertEqual(
            logic_manager.determine_report_status(result),
            {
                "status": "READY_FOR_REVIEW",
                "clarification_codes": [],
            },
        )

    def test_error_result_is_rejected_by_logic_manager(self):
        result = ai_manager.make_result(
            "report-1",
            error=RuntimeError("offline"),
        )

        self.assertEqual(result["status"], "error")
        self.assertFalse(logic_manager.validate_ai_output(result))
        self.assertEqual(
            logic_manager.determine_report_status(result)["status"],
            "AI_FAILED",
        )

    def test_process_report_returns_consistent_result_if_client_setup_fails(self):
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

        self.assertEqual(
            result,
            ai_manager.make_result(
                "report-1",
                error=RuntimeError("API key is missing"),
            ),
        )

    def test_analyze_incident_stops_after_max_attempts(self):
        class FakeCompletions:
            calls = 0

            def create(self, **kwargs):
                self.calls += 1
                message = SimpleNamespace(content='{"invalid": true}')
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=message)]
                )

        completions = FakeCompletions()
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )

        with patch.object(ai_manager.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "failed after"):
                ai_manager.analyze_incident(client, {})

        self.assertEqual(completions.calls, ai_manager.MAX_ATTEMPTS)

    def test_analyze_incident_retries_connection_failure(self):
        class FakeCompletions:
            calls = 0

            def create(self, **kwargs):
                self.calls += 1
                if self.calls < 3:
                    raise groq.APIConnectionError(
                        message="connection interrupted",
                        request=httpx.Request(
                            "POST",
                            "https://api.groq.com/openai/v1/chat/completions",
                        ),
                    )
                message = SimpleNamespace(content=json.dumps(VALID_FIELDS))
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=message)]
                )

        completions = FakeCompletions()
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )

        with patch.object(ai_manager.time, "sleep"):
            result = ai_manager.analyze_incident(client, {})

        self.assertEqual(result, VALID_FIELDS)
        self.assertEqual(completions.calls, 3)

    def test_analyze_incident_does_not_retry_non_retryable_api_error(self):
        class FakeCompletions:
            calls = 0

            def create(self, **kwargs):
                self.calls += 1
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

        completions = FakeCompletions()
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )

        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            ai_manager.analyze_incident(client, {})

        self.assertEqual(completions.calls, 1)


if __name__ == "__main__":
    unittest.main()
