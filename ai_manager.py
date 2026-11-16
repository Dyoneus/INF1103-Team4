"""AI Manager for SafeReport.

Turns a free-text safety observation into fixed structured fields using an AI
model. The model vendor is pluggable: AIManager only talks to the AIProvider
interface, so switching from Groq to another vendor does not touch the
retry, validation or prompt logic.

Classes
-------
AIProvider                  interface every vendor adapter implements
ChatCompletionsProvider     shared code for SDKs with chat.completions.create
GroqProvider                Groq adapter (default)
OpenAIProvider              OpenAI adapter; base_url also covers compatible vendors
AIConfig                    retry/timeout settings
ResponseValidator           checks the model's JSON against the allowed schema
PromptBuilder               builds the instruction text sent to the model
PhotoLoader                 finds consented photos and encodes them for the model
AIManager                   main entry point: analyze_incident / make_result
ReportBatchAnalyzer         standalone batch mode: reports/*.json -> ai_output.json

Choosing a provider without code changes (environment variables):
    AI_PROVIDER      groq (default) | openai
    AI_MODEL         model name (required for openai, optional for groq)
    AI_BASE_URL      optional, openai only: point at an OpenAI-compatible vendor
    AI_API_KEY_ENV   optional, openai only: name of the key variable
                     (default OPENAI_API_KEY)

The module-level functions at the bottom are transitional wrappers so that
main.py and the existing tests, which call ai_manager.<function>(...), keep
working. Delete them once main.py holds its own AIManager instance.
"""

import base64
import json
import logging
import mimetypes
import os
import random
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import groq
from groq import Groq

import io_manager

logger = logging.getLogger(__name__)

EXTRACTED_FIELDS = [
    "issue_clarity",
    "location_quality",
    "date_quality",
    "time_quality",
    "safety_category",
]

ALLOWED_VALUES = {
    "issue_clarity": ["CLEAR", "UNCLEAR"],
    "location_quality": ["ADEQUATE", "VAGUE", "MISSING"],
    "date_quality": ["EXACT", "APPROXIMATE", "MISSING"],
    "time_quality": ["EXACT", "APPROXIMATE", "MISSING"],
    "safety_category": [
        "FIRE",
        "ELECTRICAL",
        "SLIP_TRIP_FALL",
        "STRUCTURAL",
        "EQUIPMENT",
        "CHEMICAL",
        "ENVIRONMENTAL",
        "OTHER",
        "UNCLEAR",
    ],
}


@dataclass(frozen=True)
class AIConfig:
    """Vendor-neutral settings (frozen = cannot change by accident)."""

    max_attempts: int = 3        # total tries per report (first try + retries)
    request_timeout: int = 30    # seconds per API call
    max_backoff: int = 30        # cap on any single wait between attempts


# Old constant names, so other modules and tests that read them still work.
_DEFAULT_CONFIG = AIConfig()
MAX_ATTEMPTS = _DEFAULT_CONFIG.max_attempts
REQUEST_TIMEOUT = _DEFAULT_CONFIG.request_timeout
MAX_BACKOFF = _DEFAULT_CONFIG.max_backoff


# --- Provider layer ---------------------------------------------------------
# AIManager only knows these two error types. Each provider translates its own
# SDK's exceptions into them, so the retry loop never mentions a vendor.

class ProviderError(RuntimeError):
    """A failure that retrying will not fix (bad key, bad request, ...)."""


class RetryableProviderError(Exception):
    """A temporary failure worth retrying (network, rate limit, 5xx)."""

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after  # seconds the vendor asked us to wait


class AIProvider(ABC):
    """What AIManager needs from any AI vendor."""

    @abstractmethod
    def complete_json(self, prompt, image_urls=()):
        """Send the prompt (plus images as data URLs); return the raw reply text.

        Must raise RetryableProviderError for temporary failures and
        ProviderError for permanent ones. May raise ValueError if the vendor
        returned nothing usable (treated as retryable).
        """

    def ensure_ready(self):
        """Raise RuntimeError early if setup (e.g. an API key) is missing."""


class ChatCompletionsProvider(AIProvider):
    """Shared code for SDKs that expose client.chat.completions.create.

    Groq and OpenAI (and vendors copying OpenAI's API) all work this way, so
    subclasses only say how to build the client and which SDK module's
    exceptions to translate.
    """

    def __init__(self, model, client=None, timeout=REQUEST_TIMEOUT):
        self._model = model
        self._client = client
        self._timeout = timeout

    @abstractmethod
    def _sdk(self):
        """Return the vendor SDK module (used to recognise its exceptions)."""

    @abstractmethod
    def _create_client(self):
        """Build the vendor client; raise RuntimeError if the API key is missing."""

    def get_client(self):
        """Return the client, creating it on first use."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def ensure_ready(self):
        self.get_client()

    def complete_json(self, prompt, image_urls=()):
        client = self.get_client()
        sdk = self._sdk()

        content = [{"type": "text", "text": prompt}]
        content += [
            {"type": "image_url", "image_url": {"url": url}}
            for url in image_urls
        ]

        try:
            response = client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": content}],
                temperature=0,
                response_format={"type": "json_object"},
            )
        except (
            sdk.APIConnectionError,   # includes timeouts
            sdk.RateLimitError,
            sdk.InternalServerError,  # 5xx
        ) as exc:
            raise RetryableProviderError(
                str(exc), retry_after=self._retry_after(exc)
            ) from exc
        except sdk.APIStatusError as exc:
            raise ProviderError(
                f"Non-retryable API error (HTTP {exc.status_code}): {exc}"
            ) from exc

        if not response.choices:
            raise ValueError("AI returned no choices.")

        return response.choices[0].message.content

    @staticmethod
    def _retry_after(exc):
        response = getattr(exc, "response", None)
        if response is None:
            return None
        try:
            return float(response.headers.get("retry-after"))
        except (TypeError, ValueError):
            return None


class GroqProvider(ChatCompletionsProvider):
    DEFAULT_MODEL = "qwen/qwen3.8-27b"
    API_KEY_ENV = "GROQ_API_KEY"

    def __init__(self, model=None, client=None, timeout=REQUEST_TIMEOUT):
        super().__init__(model or self.DEFAULT_MODEL, client, timeout)

    @classmethod
    def from_env(cls, client=None, timeout=REQUEST_TIMEOUT):
        return cls(model=os.environ.get("AI_MODEL") or None,
                   client=client, timeout=timeout)

    def _sdk(self):
        return groq

    def _create_client(self):
        api_key = os.environ.get(self.API_KEY_ENV)

        if not api_key:
            raise RuntimeError(
                f"{self.API_KEY_ENV} is not configured. "
                "Set the environment variable before running the program."
            )

        return Groq(api_key=api_key, timeout=self._timeout, max_retries=0)


class OpenAIProvider(ChatCompletionsProvider):
    """OpenAI, or any vendor with an OpenAI-compatible API (set base_url).

    The model has no default on purpose: model names differ per vendor and
    change often, so the caller must choose one.
    """

    def __init__(
        self,
        model,
        client=None,
        timeout=REQUEST_TIMEOUT,
        base_url=None,
        api_key_env="OPENAI_API_KEY",
    ):
        super().__init__(model, client, timeout)
        self._base_url = base_url
        self._api_key_env = api_key_env

    @classmethod
    def from_env(cls, client=None, timeout=REQUEST_TIMEOUT):
        model = os.environ.get("AI_MODEL")

        if not model:
            raise RuntimeError(
                "AI_MODEL is not configured. The openai provider needs a "
                "model name, e.g. set AI_MODEL before running the program."
            )

        return cls(
            model=model,
            client=client,
            timeout=timeout,
            base_url=os.environ.get("AI_BASE_URL") or None,
            api_key_env=os.environ.get("AI_API_KEY_ENV") or "OPENAI_API_KEY",
        )

    def _sdk(self):
        # Imported lazily so the package is only needed if this provider is used.
        try:
            import openai
        except ImportError as exc:
            raise RuntimeError(
                "The 'openai' package is not installed. Run: pip install openai"
            ) from exc
        return openai

    def _create_client(self):
        api_key = os.environ.get(self._api_key_env)

        if not api_key:
            raise RuntimeError(
                f"{self._api_key_env} is not configured. "
                "Set the environment variable before running the program."
            )

        return self._sdk().OpenAI(
            api_key=api_key,
            base_url=self._base_url,
            timeout=self._timeout,
            max_retries=0,
        )


PROVIDERS = {"groq": GroqProvider, "openai": OpenAIProvider}


def create_provider(name=None, client=None, timeout=REQUEST_TIMEOUT):
    """Build the provider named by `name` or the AI_PROVIDER variable (default groq)."""
    key = (name or os.environ.get("AI_PROVIDER") or "groq").strip().lower()

    if key not in PROVIDERS:
        raise RuntimeError(
            f"Unknown AI provider '{key}'. Choose one of: {sorted(PROVIDERS)}"
        )

    return PROVIDERS[key].from_env(client=client, timeout=timeout)


class ResponseValidator:
    """Validates the model's raw text and returns the structured fields."""

    def __init__(self, fields=None, allowed_values=None):
        self._fields = list(fields if fields is not None else EXTRACTED_FIELDS)
        self._allowed = (
            allowed_values if allowed_values is not None else ALLOWED_VALUES
        )

    @property
    def fields(self):
        return list(self._fields)

    @property
    def allowed_values(self):
        return self._allowed

    def validate(self, text):
        """Validate the AI response and return the required structured fields."""
        if not isinstance(text, str):
            raise ValueError("AI response must be a string.")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("AI returned invalid JSON.") from exc

        if not isinstance(data, dict):
            raise ValueError("AI response must be a JSON object.")

        # Reject extra keys too, so the output matches the schema exactly.
        unexpected = [field for field in data if field not in self._fields]
        if unexpected:
            raise ValueError(
                f"AI response contains unexpected fields: {unexpected}"
            )

        missing = [f for f in self._fields if f not in data]
        if missing:
            raise ValueError(
                f"AI response is missing required fields: {missing}"
            )

        validated = {}

        for field in self._fields:
            value = data[field]

            if not isinstance(value, str):
                raise ValueError(
                    f"AI response field '{field}' must be a string."
                )

            value = value.strip().upper()

            if value not in self._allowed[field]:
                raise ValueError(
                    f"Invalid value '{value}' for field '{field}'. "
                    f"Allowed values: {self._allowed[field]}"
                )

            validated[field] = value

        return validated


class PromptBuilder:
    """Builds the instructions for structured safety observation analysis."""

    def __init__(self, fields=None, allowed_values=None):
        self._fields = list(fields if fields is not None else EXTRACTED_FIELDS)
        self._allowed = (
            allowed_values if allowed_values is not None else ALLOWED_VALUES
        )

    def build(self, incident_report):
        report_json = json.dumps(
            incident_report,
            ensure_ascii=False,
            indent=2,
        )

        allowed_section = "\n\n".join(
            f"{field}:\n" + "\n".join(f"- {v}" for v in self._allowed[field])
            for field in self._fields
        )

        return f"""

You are analysing a user's free-text safety observation.

Your task is to assess the clarity and completeness of the information
provided and organise it into the required structured fields.

Return ONLY one valid JSON object containing exactly these fields:
{json.dumps(self._fields)}

Use only the following allowed values:

{allowed_section}

Rules:
1. Analyse the user's written safety observation and the information
   available in the report.
2. Set issue_clarity to CLEAR when the safety concern can be understood.
   Otherwise, use UNCLEAR.
3. If the text is not a meaningful workplace safety observation, do not
   treat it as a valid hazard. Set issue_clarity to UNCLEAR and
   safety_category to UNCLEAR.
4. Set location_quality to MISSING when no location is provided.
   Use ADEQUATE when the location is sufficiently specific for follow-up.
   Use VAGUE when a location is provided but is not sufficiently specific.
4. Set date_quality to MISSING when no date information is provided.
   Use EXACT when a specific calendar date is given.
   Use APPROXIMATE when only relative or imprecise date information is given.
5. Set time_quality to MISSING when no time information is provided.
   Use EXACT when a specific time is given.
   Use APPROXIMATE when only a general period, such as morning or
   afternoon, is provided.
6. Choose the safety_category that best describes the concern.
7. Use OTHER when the concern is understandable but does not fit
   another listed category.
8. Use UNCLEAR for safety_category when the concern cannot be identified
   from the available information.
9. Do not invent missing information.
10. Return only the five required fields and use only their allowed values.
11. Do not provide explanations, recommendations, severity assessments,
    injury assessments, or additional fields.

Incident report:
{report_json}
""".strip()


class PhotoLoader:
    """Finds consented photos in a report and encodes them for the vision model."""

    SUPPORTED_TYPES = ("image/jpeg", "image/png", "image/webp")

    def encode(self, photo_path):
        """Encode an image as a data URL for the vision model."""
        path = Path(photo_path)

        if not path.is_file():
            raise FileNotFoundError(f"Photo file not found: {path}")

        mime_type, _ = mimetypes.guess_type(path)

        if mime_type not in self.SUPPORTED_TYPES:
            raise ValueError(f"Unsupported image type: {path}")

        with path.open("rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("utf-8")

        return f"data:{mime_type};base64,{encoded}"

    def collect_paths(self, case_details, project_dir):
        """Return photo paths from a report, only if image consent was given."""
        if case_details.get("consent_for_image_use") is not True:
            return []

        photos = case_details.get("photos", [])
        if not isinstance(photos, list):
            return []

        paths = []

        for photo in photos:
            if isinstance(photo, str):
                photo_value = photo
            elif isinstance(photo, dict):
                photo_value = (
                    photo.get("path")
                    or photo.get("file_path")
                    or photo.get("filename")
                )
            else:
                photo_value = None

            if not photo_value:
                continue

            resolved = (project_dir / photo_value).resolve()

            if project_dir not in resolved.parents:
                logger.warning(
                    "Skipping photo outside project dir: %s", photo_value
                )
                continue

            paths.append(str(resolved))

        return paths


class AIManager:
    """Sends one incident report to the AI model and returns validated fields.

    Every collaborator can be injected (handy for tests); anything left out
    gets a sensible default. The provider is created on first use, so building
    an AIManager never needs an API key.
    """

    def __init__(
        self,
        provider=None,
        config=None,
        validator=None,
        prompt_builder=None,
        photo_loader=None,
    ):
        self._provider = provider
        self._config = config or AIConfig()
        self._validator = validator or ResponseValidator()
        self._prompts = prompt_builder or PromptBuilder(
            self._validator.fields, self._validator.allowed_values
        )
        self._photos = photo_loader or PhotoLoader()

    @property
    def config(self):
        return self._config

    @property
    def photo_loader(self):
        return self._photos

    @property
    def provider(self):
        if self._provider is None:
            self._provider = create_provider(
                timeout=self._config.request_timeout
            )
        return self._provider

    def ensure_ready(self):
        """Raise RuntimeError early if the provider is not set up."""
        self.provider.ensure_ready()

    def analyze_incident(self, incident_report, photo_paths=None):
        """Analyse an incident report and return the validated fields.

        Raises RuntimeError if every attempt fails or a non-retryable error occurs.
        """
        provider = self.provider
        prompt = self._prompts.build(incident_report)
        image_urls = []

        for photo_path in photo_paths or []:
            try:
                image_urls.append(self._photos.encode(photo_path))
            except (OSError, ValueError) as exc:
                logger.warning("Skipping unusable photo %s: %s", photo_path, exc)

        max_attempts = self._config.max_attempts
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                text = provider.complete_json(prompt, image_urls)

                if not text:
                    raise ValueError("AI returned an empty response.")

                # Preserve the AI classification; the Logic Manager decides readiness.
                return self._validator.validate(text)

            except (ValueError, RetryableProviderError) as exc:
                last_error = exc
                logger.warning(
                    "Incident analysis attempt %s/%s failed: %s",
                    attempt,
                    max_attempts,
                    exc,
                )

                if attempt < max_attempts:
                    time.sleep(self._retry_delay(attempt, exc))

            # ProviderError (non-retryable) is not caught: it ends the loop.

        raise RuntimeError(
            f"Incident analysis failed after {max_attempts} attempts: {last_error}"
        ) from last_error

    def make_result(self, reference_id, fields=None, error=None):
        """Every report yields the same keys, success or failure."""
        result = {
            "reference_id": reference_id,
            "status": "error" if error else "success",
        }

        for field in self._validator.fields:
            result[field] = fields[field] if fields and not error else None

        result["error"] = str(error) if error else None
        return result

    def _retry_delay(self, attempt, exc):
        """Seconds to wait before the next attempt (honours Retry-After)."""
        retry_after = getattr(exc, "retry_after", None)
        backoff = 2 ** (attempt - 1) + random.uniform(0, 0.5)
        return min(max(backoff, retry_after or 0), self._config.max_backoff)


class ReportBatchAnalyzer:
    """Standalone batch mode: analyse every reports/*.json into ai_output.json."""

    def __init__(self, ai=None, io=None):
        self._ai = ai or AIManager()
        self._io = io or io_manager

    @staticmethod
    def get_output_path(project_dir):
        """Use persistent storage when configured; otherwise keep the local default."""
        configured_path = os.environ.get("AI_OUTPUT_PATH")
        return (
            Path(configured_path)
            if configured_path
            else project_dir / "ai_output.json"
        )

    def process_report(self, report_path, project_dir, client_error=None):
        """Process one report file. Never raises; always returns a result.

        client_error is kept so a failed client setup still yields one
        consistent error result per report.
        """
        reference_id = report_path.stem

        try:
            with report_path.open("r", encoding="utf-8") as report_file:
                report = json.load(report_file)

            if not isinstance(report, dict):
                raise ValueError("Report must be a JSON object.")

            reference_id = str(report.get("reference_id", reference_id))

            case_details = report.get("case_details", {})
            if not isinstance(case_details, dict):
                raise ValueError("Report case_details must be a JSON object.")

            if client_error is not None:
                raise client_error

            incident_data = {
                key: value
                for key, value in case_details.items()
                if key != "photos"
            }

            photo_paths = self._ai.photo_loader.collect_paths(
                case_details, project_dir
            )
            self._io.display_report_analysis_started(
                report_path.name, len(photo_paths)
            )

            fields = self._ai.analyze_incident(incident_data, photo_paths)
            return self._ai.make_result(reference_id, fields=fields)

        except Exception as exc:
            logger.error("Failed to process report %s: %s", report_path.name, exc)
            return self._ai.make_result(reference_id, error=exc)

    def run(self, project_dir):
        """Analyse every report and save all results; return a process exit code."""
        reports_dir = project_dir / "reports"
        output_path = self.get_output_path(project_dir)

        report_files = sorted(reports_dir.glob("*.json"))

        if not report_files:
            raise FileNotFoundError(f"No report JSON files found in {reports_dir}")

        client_error = None
        try:
            self._ai.ensure_ready()
        except RuntimeError as exc:
            # Keep producing one consistent error result per report if setup fails.
            client_error = exc
            logger.error("Failed to initialize AI client: %s", exc)

        results = [
            self.process_report(report_path, project_dir, client_error)
            for report_path in report_files
        ]

        tmp_path = output_path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as output_file:
            json.dump(results, output_file, ensure_ascii=False, indent=4)
        tmp_path.replace(output_path)

        successful = sum(r["status"] == "success" for r in results)
        failed = len(results) - successful

        self._io.display_analysis_summary(
            output_path=str(output_path),
            total=len(results),
            successful=successful,
            failed=failed,
        )

        return 0 if failed == 0 else 1


# --- Transitional wrappers -------------------------------------------------
# main.py and the existing tests still call ai_manager.<function>(...).
# Each wrapper just builds the matching class and delegates, so all behaviour
# lives in the classes above. Delete this block once main.py creates and holds
# its own AIManager instance.

def get_client():
    return create_provider().get_client()


def validate_response(text):
    return ResponseValidator().validate(text)


def build_prompt(incident_report):
    return PromptBuilder().build(incident_report)


def encode_image(photo_path):
    return PhotoLoader().encode(photo_path)


def collect_photo_paths(case_details, project_dir):
    return PhotoLoader().collect_paths(case_details, project_dir)


def analyze_incident(client, incident_report, photo_paths=None):
    manager = AIManager(provider=create_provider(client=client))
    return manager.analyze_incident(incident_report, photo_paths)


def make_result(reference_id, fields=None, error=None):
    return AIManager().make_result(reference_id, fields=fields, error=error)


def process_report(client, report_path, project_dir, client_error=None):
    analyzer = ReportBatchAnalyzer(
        ai=AIManager(provider=create_provider(client=client))
    )
    return analyzer.process_report(report_path, project_dir, client_error)


def get_output_path(project_dir):
    return ReportBatchAnalyzer.get_output_path(project_dir)


def main():
    """Analyse every report and save all results to ai_output.json."""
    project_dir = Path(__file__).resolve().parent
    return ReportBatchAnalyzer().run(project_dir)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        sys.exit(main())
    except Exception as exc:
        logger.error("Incident analysis failed: %s", exc)
        io_manager.display_analysis_error(str(exc))
        sys.exit(2)
