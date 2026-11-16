"""JSON storage for SafeReport"""

import json
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from storage_interface import StorageInterface

REPORTS_DIR = Path("reports")

class ReportStorage(StorageInterface):
    def __init__(self, reports_dir=None):
        if reports_dir is None:
            reports_dir = REPORTS_DIR
        self._reports_dir = Path(reports_dir)

    @property
    def reports_dir(self):
        return self._reports_dir

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

    def read_report(self, report_path):
        try:
            with Path(report_path).open("r", encoding="utf-8") as file:
                return json.load(file)

        except (OSError, json.JSONDecodeError, UnicodeError):
            return None

    def delete_report(self, reference_id):
        """Remove a report's JSON file and its photo folder.

        Returns False only when the JSON file exists but cannot be removed.
        A leftover photo folder is logged, not treated as a failure.
        """
        report_path = self.reports_dir / f"{reference_id}.json"

        try:
            report_path.unlink(missing_ok=True)
        except OSError:
            return False

        photos_root = (self.reports_dir / "photos").resolve()
        photo_dir = (photos_root / reference_id).resolve()

        # Only ever remove this report's own folder inside reports/photos.
        if photo_dir.parent == photos_root and photo_dir.is_dir():
            try:
                shutil.rmtree(photo_dir)
            except OSError as error:
                logging.warning(
                    "Could not remove photos for %s: %s", reference_id, error
                )

        return True

    def write_report(self, report_path, report):
        temp_file = None

        try:
            report_path = Path(report_path)
            json_data = json.dumps(report, indent=4, ensure_ascii=False)

            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=report_path.parent,
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

