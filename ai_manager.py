import base64
import json
import logging
import mimetypes
import os
import time
from pathlib import Path

from groq import Groq

MODEL = "qwen/qwen3.8-27b"
MAX_ATTEMPTS = 3

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


def get_client():
    """Create a Groq client using the configured API key."""
    api_key = os.environ.get("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not configured. "
            "Set the environment variable before running the program."
        )

    return Groq(api_key=api_key)


def validate_response(text):
    """Validate the AI response and return the required structured fields."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("AI returned invalid JSON.") from exc

    if not isinstance(data, dict):
        raise ValueError("AI response must be a JSON object.")

    validated = {}

    for field in EXTRACTED_FIELDS:
        value = data.get(field)

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


def build_prompt(incident_report):
    """Build instructions for structured safety observation analysis."""
    report_json = json.dumps(
        incident_report,
        ensure_ascii=False,
        indent=2,
    )

    return f"""
You are analysing a user's free-text safety observation.

Your task is to assess the clarity and completeness of the information
provided and organise it into the required structured fields.

Return ONLY one valid JSON object containing exactly these fields:
{json.dumps(EXTRACTED_FIELDS)}

Use only the following allowed values:

issue_clarity:
- CLEAR
- UNCLEAR

location_quality:
- ADEQUATE
- VAGUE
- MISSING

date_quality:
- EXACT
- APPROXIMATE
- MISSING

time_quality:
- EXACT
- APPROXIMATE
- MISSING

safety_category:
- FIRE
- ELECTRICAL
- SLIP_TRIP_FALL
- STRUCTURAL
- EQUIPMENT
- CHEMICAL
- ENVIRONMENTAL
- OTHER
- UNCLEAR

Rules:
1. Analyse the user's written safety observation and the information
   available in the report.
2. Set issue_clarity to CLEAR when the safety concern can be understood.
   Otherwise, use UNCLEAR.
3. Set location_quality to MISSING when no location is provided.
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


def analyze_incident(incident_report, photo_paths=None):
    """Analyse an incident report and return structured JSON fields."""
    client = get_client()
    prompt = build_prompt(incident_report)

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt,
                }
            ],
        }
    ]

    if photo_paths:
        for photo_path in photo_paths:
            image_url = encode_image(photo_path)
            messages[0]["content"].append(
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                }
            )

    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content

            if not content:
                raise ValueError("AI returned an empty response.")

            return validate_response(content)

        except Exception as exc:
            last_error = exc

            logger.warning(
                "Incident analysis attempt %s/%s failed: %s",
                attempt,
                MAX_ATTEMPTS,
                exc,
            )

            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** (attempt - 1))

    raise RuntimeError(
        f"Incident analysis failed after {MAX_ATTEMPTS} attempts."
    ) from last_error

def main():
    """Load and analyse every report, then save all AI results."""
    project_dir = Path(__file__).resolve().parent
    reports_dir = project_dir / "reports"
    output_path = project_dir / "ai_output.json"

    report_files = sorted(reports_dir.glob("*.json"))

    if not report_files:
        raise FileNotFoundError(
            f"No report JSON files found in {reports_dir}"
        )

    results = []

    for report_path in report_files:
        print(f"\nLoading report: {report_path.name}")

        try:
            with report_path.open("r", encoding="utf-8") as report_file:
                report = json.load(report_file)

            case_details = report.get("case_details", {})

            if not isinstance(case_details, dict):
                raise ValueError(
                    "Report case_details must be a JSON object."
                )

            incident_data = {
                key: value
                for key, value in case_details.items()
                if key != "photos"
            }

            photo_paths = []

            if case_details.get("consent_for_image_use") is True:
                photos = case_details.get("photos", [])

                if isinstance(photos, list):
                    for photo in photos:
                        if isinstance(photo, str):
                            photo_paths.append(
                                str(project_dir / photo)
                            )

                        elif isinstance(photo, dict):
                            photo_value = (
                                photo.get("path")
                                or photo.get("file_path")
                                or photo.get("filename")
                            )

                            if photo_value:
                                photo_paths.append(
                                    str(project_dir / photo_value)
                                )

            print(
                f"Analyzing incident with {len(photo_paths)} photo(s)..."
            )

            result = analyze_incident(
                incident_data,
                photo_paths=photo_paths,
            )

            result["reference_id"] = report.get(
                "reference_id",
                report_path.stem,
            )

            results.append(result)
            print(f"Successfully analysed: {report_path.name}")

        except Exception as exc:
            logger.exception(
                "Failed to process report: %s",
                report_path.name,
            )

            results.append({
                "reference_id": report_path.stem,
                "error": str(exc),
            })

    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(results, output_file, ensure_ascii=False, indent=4)

    successful = sum("error" not in result for result in results)
    failed = len(results) - successful

    print(f"\nAI results saved to: {output_path}")
    print(f"Total reports: {len(results)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("Incident analysis failed.")
        print(f"Error: {exc}")
