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
    GeminiProvider,
    GroqProvider,
    OpenAIProvider,
    PhotoLoader,
    PromptBuilder,
    ProviderError,
    ReportBatchAnalyzer,
    ResponseValidator,
    RetryableProviderError,
    create_provider,
    create_providers,
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

    def __init__(self, *outcomes, name="fake"):
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = 0
        self.last_image_urls = None
        self.last_prompt = None

    def complete_json(self, prompt, image_urls=()):
        self.calls += 1
        self.last_prompt = prompt
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


# --- Failover between providers ----------------------------------------------

def test_next_provider_steps_in_when_first_fails_permanently():
    groq = FakeProvider(ProviderError("HTTP 401"), name="groq")
    gemini = FakeProvider(json.dumps(VALID_FIELDS), name="gemini")

    manager = AIManager(providers=[groq, gemini])

    assert manager.analyze_incident({}) == VALID_FIELDS
    assert groq.calls == 1 and gemini.calls == 1


def test_gemini_first_and_groq_as_backup_also_works():
    gemini = FakeProvider(ProviderError("HTTP 503"), name="gemini")
    groq = FakeProvider(json.dumps(VALID_FIELDS), name="groq")

    assert AIManager(providers=[gemini, groq]).analyze_incident({}) == VALID_FIELDS


def test_first_provider_is_not_retried_when_a_backup_exists():
    groq = FakeProvider(
        RetryableProviderError("busy"), RetryableProviderError("busy"), name="groq"
    )
    gemini = FakeProvider(json.dumps(VALID_FIELDS), name="gemini")

    AIManager(providers=[groq, gemini]).analyze_incident({})

    assert groq.calls == 1  # fallback_attempts defaults to 1


def test_last_provider_still_gets_full_retries():
    groq = FakeProvider(ProviderError("HTTP 401"), name="groq")
    gemini = FakeProvider(
        RetryableProviderError("busy"),
        RetryableProviderError("busy"),
        json.dumps(VALID_FIELDS),
        name="gemini",
    )

    with patch.object(ai_manager.time, "sleep"):
        result = AIManager(providers=[groq, gemini]).analyze_incident({})

    assert result == VALID_FIELDS and gemini.calls == 3


def test_bad_json_from_first_provider_falls_back_to_second():
    groq = FakeProvider('{"not": "the schema"}', name="groq")
    gemini = FakeProvider(json.dumps(VALID_FIELDS), name="gemini")

    assert AIManager(providers=[groq, gemini]).analyze_incident({}) == VALID_FIELDS


def test_error_names_every_provider_when_all_fail():
    groq = FakeProvider(ProviderError("HTTP 401"), name="groq")
    gemini = FakeProvider(ProviderError("HTTP 429"), name="gemini")

    with pytest.raises(RuntimeError) as error:
        AIManager(providers=[groq, gemini]).analyze_incident({})

    message = str(error.value)
    assert "All AI providers failed" in message
    assert "groq failed: HTTP 401" in message
    assert "gemini failed: HTTP 429" in message


def test_single_provider_keeps_its_original_error():
    only = FakeProvider(ProviderError("HTTP 401"), name="groq")

    with pytest.raises(RuntimeError) as error:
        AIManager(providers=[only]).analyze_incident({})

    assert str(error.value) == "HTTP 401"


def test_ensure_ready_passes_if_any_provider_is_usable():
    class NotReady(FakeProvider):
        def ensure_ready(self):
            raise RuntimeError("GROQ_API_KEY is not configured.")

    AIManager(providers=[NotReady(name="groq"), FakeProvider(name="gemini")]).ensure_ready()


def test_ensure_ready_lists_every_problem_when_none_usable():
    class NotReady(FakeProvider):
        def ensure_ready(self):
            raise RuntimeError(f"{self.name} key missing")

    manager = AIManager(providers=[NotReady(name="groq"), NotReady(name="gemini")])

    with pytest.raises(RuntimeError, match="groq failed: groq key missing.*gemini failed"):
        manager.ensure_ready()


def test_ai_provider_list_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "groq, gemini")
    monkeypatch.setenv("GEMINI_MODEL", "some-gemini-model")

    providers = create_providers()

    assert [type(p) for p in providers] == [GroqProvider, GeminiProvider]
    assert [p.name for p in providers] == ["groq", "gemini"]


def test_unknown_name_in_list_is_rejected():
    with pytest.raises(RuntimeError, match="Unknown AI provider 'gemni'"):
        create_providers("groq,gemni")


def test_unconfigured_provider_does_not_break_the_chain(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    groq_client = FakeClient(json.dumps(VALID_FIELDS))
    providers = create_providers("gemini,groq")
    providers[1] = GroqProvider(client=groq_client)  # Groq works, Gemini has no model

    result = AIManager(providers=providers).analyze_incident({})

    assert result == VALID_FIELDS and groq_client.calls == 1
    assert "GEMINI_MODEL" in str(
        pytest.raises(RuntimeError, providers[0].ensure_ready).value
    )


def test_gemini_provider_points_at_google_endpoint():
    provider = GeminiProvider("some-model")

    assert provider._base_url == GeminiProvider.BASE_URL
    assert provider._api_key_env == "GEMINI_API_KEY"


def test_get_client_wrapper_returns_the_failover_manager(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    client = ai_manager.get_client()

    assert isinstance(client, AIManager)


def test_analyze_incident_wrapper_uses_a_manager_passed_as_client():
    manager = AIManager(provider=FakeProvider(json.dumps(VALID_FIELDS)))

    assert ai_manager.analyze_incident(manager, {"description": "x"}) == VALID_FIELDS


# --- Photos are mentioned in the prompt only when they are really attached ---

def test_prompt_without_photos_has_no_photo_section():
    prompt = PromptBuilder().build({"description": "wet floor"})

    assert "Photos:" not in prompt
    assert "photo" not in prompt.lower()


def test_prompt_with_photos_tells_the_model_how_to_use_them():
    prompt = PromptBuilder().build({"description": "wet floor"}, photo_count=2)

    assert "2 photo(s)" in prompt
    flat = " ".join(prompt.split())  # ignore line wrapping
    assert "from the written report only" in flat  # location/date/time stay text-based
    assert prompt.index("Photos:") < prompt.index("Incident report:")


def test_manager_mentions_photos_only_when_they_were_encoded(tmp_path):
    photo = tmp_path / "p.png"
    photo.write_bytes(b"\x89PNG")
    with_photo = FakeProvider(json.dumps(VALID_FIELDS))
    broken_photo = FakeProvider(json.dumps(VALID_FIELDS))
    no_photo = FakeProvider(json.dumps(VALID_FIELDS))

    AIManager(provider=with_photo).analyze_incident({}, [str(photo)])
    AIManager(provider=broken_photo).analyze_incident({}, [str(tmp_path / "missing.png")])
    AIManager(provider=no_photo).analyze_incident({})

    assert "1 photo(s)" in with_photo.last_prompt
    assert with_photo.last_image_urls
    assert "Photos:" not in broken_photo.last_prompt  # unreadable file: not mentioned
    assert "Photos:" not in no_photo.last_prompt
