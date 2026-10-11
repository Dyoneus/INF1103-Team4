import json
import os
import tempfile

DATA_FILE = "reports.json"


def load_reports():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            reports = json.load(file)

            if not isinstance(reports, list):
                return None
            
            return reports

    except FileNotFoundError:
        return []

    except (json.JSONDecodeError, OSError):
        return None


def save_report(report):
    reports = load_reports()

    if reports is None:
        return False

    if not isinstance(report, dict):
        return False

    reports.append(report)

    temp_file = None

    try:
        # Convert to JSON first to check if the data is valid
        json_data = json.dumps(reports, indent=4, ensure_ascii=False)

        # Save to a temporary file first
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=".",
            suffix=".tmp",
            delete=False
        ) as file:
            temp_file = file.name
            file.write(json_data)

        # Replace the original file only after saving succeeds
        os.replace(temp_file, DATA_FILE)

        return True

    except (OSError, TypeError, ValueError):
        return False

    finally:
        if temp_file is not None:
            try:
                os.remove(temp_file)
            except FileNotFoundError:
                pass
            except OSError:
                pass



def filter_by_status(status):
    reports = load_reports()

    if reports is None:
        return None

    filtered_reports = []

    for report in reports:
        if isinstance(report, dict):
            if report.get("status") == status:
                filtered_reports.append(report)

    return filtered_reports



