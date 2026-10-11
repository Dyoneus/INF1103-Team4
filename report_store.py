"""JSON storage for SafeReport"""

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

REPORTS_DIR = Path("reports")


def save_report(report: dict) -> Path:
    """Save a collected report as a JSON file and return the file's path.

    Attached photos are copied into reports/photos/<reference_id>/ so the
    report still has its evidence if the original files are moved or deleted.
    Raises OSError if the files cannot be written.
    """
    now = datetime.now()
    reference_id = f"{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"

    case_details = dict(report["case_details"])
    case_details["photos"] = _copy_photos(case_details.get("photos", []), reference_id)

    record = {
        "reference_id": reference_id,
        "submitted_at": now.isoformat(timespec="seconds"),
        "case_details": case_details,
        "reporter": report["reporter"],
    }

    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = REPORTS_DIR / f"{reference_id}.json"
    with report_path.open("w", encoding="utf-8") as file:
        json.dump(record, file, indent=2, ensure_ascii=False)

    return report_path


def _copy_photos(photo_paths: list[str], reference_id: str) -> list[str]:
    """Copy photos into the report's photo folder; return their new paths."""
    if not photo_paths:
        return []

    photo_dir = REPORTS_DIR / "photos" / reference_id
    photo_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for number, source in enumerate(photo_paths, start=1):
        destination = photo_dir / f"photo_{number}{Path(source).suffix.lower()}"
        shutil.copy2(source, destination)
        saved.append(destination.as_posix())

    return saved
