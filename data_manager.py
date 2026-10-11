import json

DATA_FILE = "reports.json"


def load_reports():
    try:
        with open(DATA_FILE, "r") as file:
            reports = json.load(file)
            return reports

    except FileNotFoundError:
        return []

    except json.JSONDecodeError:
        return None


def save_report(report):
    reports = load_reports()

    if reports is None:
        return False

    reports.append(report)

    with open(DATA_FILE, "w") as file:
        json.dump(reports, file, indent=4)
    return True


def filter_by_status(status):
    reports = load_reports()

    if reports is None:
        return None

    filtered_reports = []

    for report in reports:
        if report.get("status") == status:
            filtered_reports.append(report)

    return filtered_reports



