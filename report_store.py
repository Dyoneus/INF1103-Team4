"""JSON storage for SafeReport"""

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

REPORTS_DIR = Path("reports")


class ReportStorage:
    def __init__(self, reports_dir=None):
        if reports_dir is None:
            reports_dir = REPORTS_DIR
        self.reports_dir = Path(reports_dir)

    def save_report(self, report: dict) -> Path:
        now = datetime.now()
        reference_id = f"{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"

        case_details = dict(report["case_details"])
        case_details["photos"] = self.copy_photos(
            case_details.get("photos", []), reference_id
        )

        record = {
            "reference_id": reference_id,
            "submitted_at": now.isoformat(timespec="seconds"),
            "case_details": case_details,
            "reporter": report["reporter"],
        }

        self.reports_dir.mkdir(exist_ok=True)
        report_path = self.reports_dir / f"{reference_id}.json"

        with report_path.open("w", encoding="utf-8") as file:
            json.dump(record, file, indent=2, ensure_ascii=False)

        return report_path

    def copy_photos(self, photo_paths, reference_id):
        if not photo_paths:
            return []

        photo_dir = self.reports_dir / "photos" / reference_id
        photo_dir.mkdir(parents=True, exist_ok=True)

        saved = []

        for number, source in enumerate(photo_paths, start=1):
            destination = photo_dir / f"photo_{number}{Path(source).suffix.lower()}"
            shutil.copy2(source, destination)
            saved.append(destination.as_posix())

        return saved


def save_report(report: dict) -> Path:
    return ReportStorage().save_report(report)


def _copy_photos(photo_paths, reference_id):
    return ReportStorage().copy_photos(photo_paths, reference_id)
