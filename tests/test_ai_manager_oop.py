"""Tests for the class-based AI Manager (no network, no API key needed)."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_manager
from ai_manager import (
    AIConfig,
    AIManager,
    AIProvider,
    GroqProvider,
    OpenAIProvider,
    PhotoLoader,
    PromptBuilder,
    ProviderError,
    ReportBatchAnalyzer,
    ResponseValidator,
    RetryableProviderError,
    create_provider,
)

VALID_FIELDS = {
    "issue_clarity": "CLEAR",
    "location_quality": "ADEQUATE",
    "date_quality": "EXACT",
    "time_quality": "EXACT",
    "safety_category": "FIRE",
}


class FakeClient:
    """Stands in for Groq: replies with fixed text and counts the calls."""

    def __init__(self, text):
        self.calls = 0
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )
        self._text = text

    def _create(self, **kwargs):
        self.calls += 1
        message = SimpleNamespace(content=self._text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeProvider(AIProvider):
    """A vendor-free provider: replays scripted replies or raises scripted errors."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.last_image_urls = None

    def complete_json(self, prompt, image_urls=()):
        self.calls += 1
        self.last_image_urls = list(image_urls)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_manager_uses_injected_client_without_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    client = FakeClient(json.dumps(VALID_FIELDS))

    manager = AIManager(provider=GroqProvider(client=client))

    assert manager.analyze_incident({"description": "frayed cable"}) == VALID_FIELDS
    assert client.calls == 1


def test_default_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        AIManager().ensure_ready()


def test_config_controls_number_of_attempts():
    client = FakeClient('{"invalid": true}')
    manager = AIManager(
        provider=GroqProvider(client=client), config=AIConfig(max_attempts=2)
    )

    with patch.object(ai_manager.time, "sleep"):
        with pytest.raises(RuntimeError, match="failed after 2 attempts"):
            manager.analyze_incident({})

    assert client.calls == 2


def test_make_result_has_same_keys_for_success_and_error():
    manager = AIManager()

    ok = manager.make_result("r1", fields=VALID_FIELDS)
    bad = manager.make_result("r2", error=RuntimeError("boom"))

    assert ok.keys() == bad.keys()
    assert ok["status"] == "success" and bad["status"] == "error"
    assert bad["error"] == "boom" and bad["safety_category"] is None


def test_validator_rejects_value_outside_allowed_set():
    data = dict(VALID_FIELDS, safety_category="NOT_A_CATEGORY")

    with pytest.raises(ValueError, match="Invalid value"):
        ResponseValidator().validate(json.dumps(data))


def test_validator_accepts_custom_schema():
    validator = ResponseValidator(
        fields=["issue_clarity"],
        allowed_values={"issue_clarity": ["CLEAR", "UNCLEAR"]},
    )

    assert validator.validate('{"issue_clarity": " clear "}') == {
        "issue_clarity": "CLEAR"
    }


def test_prompt_builder_lists_every_allowed_value_and_the_report():
    prompt = PromptBuilder().build({"description": "wet floor"})

    for values in ai_manager.ALLOWED_VALUES.values():
        for value in values:
            assert f"- {value}" in prompt
    assert "wet floor" in prompt


def test_photo_loader_needs_consent(tmp_path):
    details = {"consent_for_image_use": False, "photos": ["a.jpg"]}

    assert PhotoLoader().collect_paths(details, tmp_path.resolve()) == []


def test_photo_loader_skips_paths_outside_project(tmp_path):
    project = (tmp_path / "project").resolve()
    project.mkdir()
    details = {
        "consent_for_image_use": True,
        "photos": ["inside.jpg", "../outside.jpg"],
    }

    paths = PhotoLoader().collect_paths(details, project)

    assert paths == [str(project / "inside.jpg")]


def test_photo_loader_rejects_unsupported_type(tmp_path):
    gif = tmp_path / "x.gif"
    gif.write_bytes(b"GIF89a")

    with pytest.raises(ValueError, match="Unsupported image type"):
        PhotoLoader().encode(gif)


def test_batch_analyzer_writes_one_result_per_report(
    tmp_path, monkeypatch, make_io
):
    monkeypatch.delenv("AI_OUTPUT_PATH", raising=False)
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "a.json").write_text(
        json.dumps({"reference_id": "A", "case_details": {"description": "x"}})
    )
    (reports / "b.json").write_text("not json")

    io, console = make_io()
    analyzer = ReportBatchAnalyzer(
        ai=AIManager(provider=FakeProvider(json.dumps(VALID_FIELDS))), io=io
    )

    exit_code = analyzer.run(tmp_path.resolve())

    results = json.loads((tmp_path / "ai_output.json").read_text())
    assert [r["status"] for r in results] == ["success", "error"]
    assert exit_code == 1
    assert "Successful: 1" in console.text
    assert "Failed: 1" in console.text


# --- Switching AI provider ---------------------------------------------------

def test_manager_works_with_any_provider_implementation():
    provider = FakeProvider(json.dumps(VALID_FIELDS))

    result = AIManager(provider=provider).analyze_incident({"description": "x"})

    assert result == VALID_FIELDS


def test_retryable_provider_error_is_retried():
    provider = FakeProvider(
        RetryableProviderError("rate limited", retry_after=0),
        json.dumps(VALID_FIELDS),
    )

    with patch.object(ai_manager.time, "sleep"):
        result = AIManager(provider=provider).analyze_incident({})

    assert result == VALID_FIELDS and provider.calls == 2


def test_permanent_provider_error_is_not_retried():
    provider = FakeProvider(ProviderError("HTTP 401"), json.dumps(VALID_FIELDS))

    with pytest.raises(RuntimeError, match="HTTP 401"):
        AIManager(provider=provider).analyze_incident({})

    assert provider.calls == 1


def test_retry_delay_honours_retry_after_but_respects_cap():
    manager = AIManager(config=AIConfig(max_backoff=10))

    assert manager._retry_delay(1, RetryableProviderError("x", retry_after=7)) == 7
    assert manager._retry_delay(1, RetryableProviderError("x", retry_after=99)) == 10


def test_photos_are_passed_to_provider_as_data_urls(tmp_path):
    photo = tmp_path / "p.png"
    photo.write_bytes(b"\x89PNG")
    provider = FakeProvider(json.dumps(VALID_FIELDS))

    AIManager(provider=provider).analyze_incident({}, [str(photo)])

    assert provider.last_image_urls[0].startswith("data:image/png;base64,")


def test_factory_defaults_to_groq(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)

    assert isinstance(create_provider(), GroqProvider)


def test_factory_picks_openai_from_environment(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "some-model")

    assert isinstance(create_provider(), OpenAIProvider)


def test_openai_provider_requires_a_model(monkeypatch):
    monkeypatch.delenv("AI_MODEL", raising=False)

    with pytest.raises(RuntimeError, match="AI_MODEL"):
        create_provider("openai")


def test_factory_rejects_unknown_provider():
    with pytest.raises(RuntimeError, match="Unknown AI provider"):
        create_provider("nope")


def test_make_result_does_not_need_a_configured_provider(monkeypatch):
    # main.py builds failure results when setup is broken, so this must not raise.
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.delenv("AI_MODEL", raising=False)

    result = ai_manager.make_result("r1", error=RuntimeError("CONFIG_MISSING"))

    assert result["status"] == "error"


def test_openai_provider_translates_errors_and_reads_reply():
    openai = pytest.importorskip("openai")
    import httpx

    request = httpx.Request("POST", "https://example.test/v1/chat/completions")

    def make_client(effect):
        return SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=effect)))

    def timeout(**kwargs):
        raise openai.APIConnectionError(message="down", request=request)

    def unauthorized(**kwargs):
        raise openai.APIStatusError(
            "bad key", response=httpx.Response(401, request=request), body=None)

    def ok(**kwargs):
        message = SimpleNamespace(content="REPLY")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    with pytest.raises(RetryableProviderError):
        OpenAIProvider("m", client=make_client(timeout)).complete_json("p")

    with pytest.raises(ProviderError, match="HTTP 401"):
        OpenAIProvider("m", client=make_client(unauthorized)).complete_json("p")

    assert OpenAIProvider("m", client=make_client(ok)).complete_json("p") == "REPLY"
