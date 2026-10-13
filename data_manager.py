import json
import os
import tempfile
from pathlib import Path
from report_store import save_report as save_raw_report

REPORTS_DIR = Path("reports")

def create_report(report):
    """Save a new raw report and return its file path."""
    return save_raw_report(report)

def load_reports():
    if not REPORTS_DIR.exists():
        return []

    if not REPORTS_DIR.is_dir():
        return None

    reports = []
    
    try:
        for reports_path in sorted(REPORTS_DIR.glob("*.json")):
            with reports_path.open("r", encoding="utf-8") as file:
                report = json.load(file)

            if not isinstance(report, dict):
                return None

            reports.append(report)
            
        return reports

    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def _write_report(report_path, report):
    temp_file = None

    try:
        json_data = json.dumps(report, indent=4, ensure_ascii=False)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=REPORTS_DIR,
            suffix=".tmp",
            delete=False
        ) as file:
            temp_file = file.name
            file.write(json_data)

        os.replace(temp_file, report_path)
        return True

    except (OSError, TypeError, ValueError):
        return False

    finally:
        if temp_file is not None:
            try:
                os.remove(temp_file)
            except OSError:
                pass


def update_report(reference_id, updated_data, case_changes=None):
    if not isinstance(reference_id, str) or not reference_id.strip():
        return False

    if "/" in reference_id or "\\" in reference_id:
        return False

    if reference_id in (".", ".."):
        return False

    if not isinstance(updated_data, dict):
        return False

    if "reference_id" in updated_data:
        return False

    # Only allow AI and Logic results to be updated.
    if not set(updated_data).issubset({"ai_result", "assessment"}):
        return False

    if case_changes is not None:
        if not isinstance(case_changes, dict) or not case_changes:
            return False
        if not set(case_changes).issubset({
            "description", "workplace_location", "incident_datetime"
        }):
            return False
        if any(not isinstance(value, str) or not value.strip()
               for value in case_changes.values()):
            return False
    
    report_path = REPORTS_DIR / (reference_id + ".json")

    try:
        if not report_path.is_file():
            return False

        with report_path.open("r", encoding="utf-8") as file:
            report = json.load(file)

        if not isinstance(report, dict):
            return False

        if report.get("reference_id") != reference_id:
            return False

        if case_changes is not None:
            if not isinstance(report.get("case_details"), dict):
                return False
            report["case_details"].update(case_changes)
            # Persist corrections before contacting AI. A cancelled or failed
            # assessment can then be resumed through the retry menu.
            report["ai_result"] = None
            report["assessment"] = {
                "status": "AI_FAILED", "clarification_codes": []
            }

        report.update(updated_data)

        return _write_report(report_path, report)

    except (OSError, json.JSONDecodeError, UnicodeError):
        return False


def save_clarifications(reference_id, changes):
    """Atomically save corrected details and invalidate the old assessment."""
    return update_report(reference_id, {}, case_changes=changes)


def save_report(reference_id, ai_result, assessment):
    if not isinstance(ai_result, dict):
        return False

    if not isinstance(assessment, dict):
        return False

    if not isinstance(assessment.get("status"), str):
        return False

    if not isinstance(assessment.get("clarification_codes"), list):
        return False

    updated_data = {
        "ai_result": ai_result,
        "assessment": assessment
    }

    return update_report(reference_id, updated_data)


def filter_by_status(status):
    reports = load_reports()

    if reports is None:
        return None

    filtered_reports = []

    for report in reports:
        assessment = report.get("assessment", {})

        if isinstance(assessment, dict):
            if assessment.get("status") == status:
                filtered_reports.append(report)

    return filtered_reports


def get_failed_ai_reports():
    return filter_by_status("AI_FAILED")
