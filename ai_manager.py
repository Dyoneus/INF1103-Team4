import base64
import json
import logging
import mimetypes
import os
import random
import re
import sys
import time
from pathlib import Path

import groq
from groq import Groq

import constants
from constants import ALLOWED_VALUES, EXTRACTED_FIELDS

MODEL = "qwen/qwen3.8-27b"
MAX_ATTEMPTS = 3 # total tries per report (first try + retries)
REQUEST_TIMEOUT = 30  # seconds# seconds per API call
MAX_BACKOFF = 30 #cap on any single wait between attempts

logger = logging.getLogger(__name__)

RETRYABLE_API_ERRORS = (
    groq.APIConnectionError,   # includes APITimeoutError
    groq.RateLimitError,
    groq.InternalServerError,  # 5xx
)

def get_client():
    """Create a Groq client using the configured API key."""
    api_key = os.environ.get("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not configured. "
            "Set the environment variable before running the program."
        )

    return Groq(api_key=api_key, timeout=REQUEST_TIMEOUT, max_retries=0)

def validate_response(text):
    """Validate the AI response and return the required structured fields."""
    if not isinstance(text, str):
        raise ValueError("AI response must be a string.")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("AI returned invalid JSON.") from exc

    if not isinstance(data, dict):
        raise ValueError("AI response must be a JSON object.")

    # Reject extra keys too, so the AI output matches the required schema exactly.
    unexpected = [field for field in data if field not in EXTRACTED_FIELDS]
    if unexpected:
        raise ValueError(
            f"AI response contains unexpected fields: {unexpected}"
        )

    missing = [f for f in EXTRACTED_FIELDS if f not in data]
    if missing:
        raise ValueError(
            f"AI response is missing required fields: {missing}"
        )

    validated = {}

    for field in EXTRACTED_FIELDS:
        value = data[field]

        if not isinstance(value, str):
            raise ValueError(
                f"AI response field '{field}' must be a string."
            )

        value = value.strip().upper()

        if value not in ALLOWED_VALUES[field]:
            raise ValueError(
                f"Invalid value '{value}' for field '{field}'. "
                f"Allowed values: {ALLOWED_VALUES[field]}"
            )

        validated[field] = value

    return validated


def looks_like_safety_observation(description):
    """Return True when a free-text report appears to describe a genuine hazard."""
    if not isinstance(description, str):
        return False

    cleaned = re.sub(r"[^a-z0-9\s]", " ", description.lower())
    words = cleaned.split()

    if not words:
        return False

    if len(words) < 3:
        return False

    safety_keywords = (
        "accident", "alert", "barrier", "broken", "cable", "chemical", "collapse",
        "danger", "damage", "electric", "electrical", "equipment", "exposed",
        "fall", "fire", "gas", "hazard", "injury", "leak", "loose", "machine",
        "noise", "obstruction", "safety", "slip", "smoke", "spark", "spill",
        "trip", "unsafe", "ventilation", "warning", "workers", "workplace",
    )

    return any(keyword in cleaned for keyword in safety_keywords)


def enforce_safety_context(incident_report, fields):
    """Reject non-safety observations even when the model returns allowed labels."""
    if not isinstance(fields, dict):
        return fields

    description = incident_report.get("description", "") if isinstance(incident_report, dict) else ""
    if not description or not str(description).strip():
        return fields
    if looks_like_safety_observation(description):
        return fields

    fields = dict(fields)
    if fields.get("issue_clarity") == "CLEAR":
        fields["issue_clarity"] = "UNCLEAR"
    if fields.get("safety_category") not in (None, "UNCLEAR"):
        fields["safety_category"] = "UNCLEAR"
    return fields


def build_prompt(incident_report):
    """Build instructions for structured safety observation analysis."""
    report_json = json.dumps(
        incident_report,
        ensure_ascii=False,
        indent=2,
    )

    allowed_section = "\n\n".join(
        f"{field}:\n" + "\n".join(f"- {v}" for v in ALLOWED_VALUES[field])
        for field in EXTRACTED_FIELDS
    )

    return f"""

You are analysing a user's free-text safety observation.

Your task is to assess the clarity and completeness of the information
provided and organise it into the required structured fields.

Return ONLY one valid JSON object containing exactly these fields:
{json.dumps(EXTRACTED_FIELDS)}

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


def encode_image(photo_path):
    """Encode an image as a data URL for the vision model."""
    path = Path(photo_path)

    if not path.is_file():
        raise FileNotFoundError(f"Photo file not found: {path}")

    mime_type, _ = mimetypes.guess_type(path)

    if mime_type not in ("image/jpeg", "image/png", "image/webp"):
        raise ValueError(f"Unsupported image type: {path}")

    with path.open("rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("utf-8")

    return f"data:{mime_type};base64,{encoded}"

def collect_photo_paths(case_details, project_dir):
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
            logger.warning("Skipping photo outside project dir: %s", photo_value)
            continue

        paths.append(str(resolved))

    return paths

def _retry_delay(attempt, exc):
    """Seconds to wait before the next attempt (honours Retry-After)."""
    retry_after = None

    response = getattr(exc, "response", None)
    if response is not None:
        try:
            retry_after = float(response.headers.get("retry-after"))
        except (TypeError, ValueError):
            retry_after = None

    backoff = 2 ** (attempt - 1) + random.uniform(0, 0.5)
    return min(max(backoff, retry_after or 0), MAX_BACKOFF)

def analyze_incident(client, incident_report, photo_paths=None):
    """Analyse an incident report and return the validated fields.

    Raises RuntimeError if every attempt fails or a non-retryable error occurs.
    """
    content = [{"type": "text", "text": build_prompt(incident_report)}]

    for photo_path in photo_paths or []:
        try:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": encode_image(photo_path)},
                }
            )
        except (OSError, ValueError) as exc:
            logger.warning("Skipping unusable photo %s: %s", photo_path, exc)

    messages = [{"role": "user", "content": content}]
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )

            if not response.choices:
                raise ValueError("AI returned no choices.")

            text = response.choices[0].message.content

            if not text:
                raise ValueError("AI returned an empty response.")

            fields = validate_response(text)
            return enforce_safety_context(incident_report, fields)

        except (ValueError, *RETRYABLE_API_ERRORS) as exc:
            last_error = exc
            logger.warning(
                "Incident analysis attempt %s/%s failed: %s",
                attempt,
                MAX_ATTEMPTS,
                exc,
            )

            if attempt < MAX_ATTEMPTS:
                time.sleep(_retry_delay(attempt, exc))

        except groq.APIStatusError as exc:
            raise RuntimeError(
                f"Non-retryable API error (HTTP {exc.status_code}): {exc}"
            ) from exc

    raise RuntimeError(
        f"Incident analysis failed after {MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error

def make_result(reference_id, fields=None, error=None):
    """Every report yields the same keys, success or failure."""
    result = {
        "reference_id": reference_id,
        "status": "error" if error else "success",
    }

    for field in EXTRACTED_FIELDS:
        result[field] = fields[field] if fields and not error else None

    result["error"] = str(error) if error else None
    return result


def process_report(client, report_path, project_dir, client_error=None):
    """Process one report file. Never raises; always returns a result."""
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

        photo_paths = collect_photo_paths(case_details, project_dir)
        print(f"Analyzing {report_path.name} with {len(photo_paths)} photo(s)...")

        fields = analyze_incident(client, incident_data, photo_paths)
        return make_result(reference_id, fields=fields)

    except Exception as exc:
        logger.error("Failed to process report %s: %s", report_path.name, exc)
        return make_result(reference_id, error=exc)

def get_output_path(project_dir):
    """Use persistent storage when configured; otherwise keep the local default."""
    configured_path = os.environ.get("AI_OUTPUT_PATH")
    return Path(configured_path) if configured_path else project_dir / "ai_output.json"

def main():
    """Analyse every report and save all results to ai_output.json."""
    project_dir = Path(__file__).resolve().parent
    reports_dir = project_dir / constants.REPORTS_DIR
    output_path = get_output_path(project_dir)

    report_files = sorted(reports_dir.glob("*.json"))

    if not report_files:
        raise FileNotFoundError(f"No report JSON files found in {reports_dir}")

    client_error = None
    try:
        client = get_client()
    except RuntimeError as exc:
        # Keep producing one consistent error result per report if setup fails.
        client = None
        client_error = exc
        logger.error("Failed to initialize AI client: %s", exc)

    results = [
        process_report(client, report_path, project_dir, client_error)
        for report_path in report_files
    ]

    tmp_path = output_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as output_file:
        json.dump(results, output_file, ensure_ascii=False, indent=4)
    tmp_path.replace(output_path)

    successful = sum(r["status"] == "success" for r in results)
    failed = len(results) - successful

    print(f"\nAI results saved to: {output_path}")
    print(f"Total reports: {len(results)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        sys.exit(main())
    except Exception as exc:
        logger.error("Incident analysis failed: %s", exc)
        print(f"Error: {exc}")
        sys.exit(2)