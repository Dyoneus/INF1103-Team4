import json

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

    try:
        with open(DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(reports, file, indent=4, ensure_ascii=False)
        return True

    except(OSError,TypeError, ValueError):
        return False


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



