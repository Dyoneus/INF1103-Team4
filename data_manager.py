import json
from pathlib import Path
from report_store import ReportStorage
from database_manager import DatabaseManager
import logging

REPORTS_DIR = Path("reports")

class DataManager:
    def __init__(self, database=None, storage=None):
        if database is None:
            database = DatabaseManager()

        if storage is None:
            storage = ReportStorage(REPORTS_DIR)

        self._database = database
        self._storage = storage
        self._database_ready = self.database.initialize_database()

        # Import legacy JSON reports once at startup
        self._legacy_import_ok = self.migrate_reports()

        if self.database_ready and not self.legacy_import_ok:
            logging.warning("Some legacy JSON reports could not be imported.")

    @property
    def database(self):
        return self._database

    @property
    def storage(self):
        return self._storage

    @property
    def database_ready(self):
        return self._database_ready

    @property
    def legacy_import_ok(self):
        return self._legacy_import_ok

    def migrate_reports(self):
        if not self.database_ready:
            return False

        if not self.storage.reports_dir.exists():
            return True

        if not self.storage.reports_dir.is_dir():
            return False

        existing_reports = self.database.load_reports()

        if existing_reports is None:
            return False

        existing_ids = {
            report["reference_id"]
            for report in existing_reports
        }

        try:
            for report_path in sorted(self.storage.reports_dir.glob("*.json")):
                report = self.storage.read_report(report_path)

                if not isinstance(report, dict):
                    return False

                reference_id = report.get("reference_id")

                if not isinstance(reference_id, str):
                    return False

                if reference_id != report_path.stem:
                    return False

                if reference_id not in existing_ids:
                    if not self.database.create_report(report):
                        return False

                    existing_ids.add(reference_id)

            return True

        except (OSError, json.JSONDecodeError, UnicodeError, KeyError, TypeError):
            return False
    
    def load_reports(self):
        # Read directly from SQLite. Legacy JSON reports are imported
        # once at startup by migrate_reports().
        if not self.database_ready:
            return None

        return self.database.load_reports()

    def filter_by_status(self, status):
        reports = self.load_reports()

        if reports is None:
            return None

        filtered_reports = []

        for report in reports:
            assessment = report.get("assessment", {})

            if isinstance(assessment, dict):
                if assessment.get("status") == status:
                    filtered_reports.append(report)

        return filtered_reports


    def get_failed_ai_reports(self):
        return self.filter_by_status("AI_FAILED")


    def create_report(self, report):
        # save to JSON and SQLite. Raise OSError on failure
        if not self.database_ready:
            raise OSError("SQLite database is not ready.")

        try:
            report_path = self.storage.save_report(report)

            if not report_path:
                raise OSError("No report path was returned.")

            saved_report = self.storage.read_report(report_path)

            if not isinstance(saved_report, dict):
                raise OSError("Could not read the saved JSON report.")

            if not self.database.create_report(saved_report):
                # Preserve JSON and photos for recovery.
                raise OSError(
                    "SQLite save failed; JSON retained for recovery."
                )

            return report_path

        except (OSError, json.JSONDecodeError, UnicodeError, TypeError, KeyError) as error:
            raise OSError("Could not save the report.") from error


    def update_report(self, reference_id, updated_data, case_changes=None):
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
        
        report_path = self.storage.reports_dir / (reference_id + ".json")

        try:
            if not report_path.is_file():
                return False

            report = self.storage.read_report(report_path)

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

            if not self.database_ready:
                return False

            # Keep the original SQLite report for recovery.
            existing_reports = self.database.load_reports()

            if existing_reports is None:
                return False

            original_report = None

            for existing_report in existing_reports:
                if existing_report.get("reference_id") == reference_id:
                    original_report = existing_report
                    break

            if original_report is None:
                return False

            if not self.database.update_report(reference_id, report):
                return False

            if not self.storage.write_report(report_path, report):
                # print("Failed to update report in JSON.")

                # Restore the previous SQLite report.
                if not self.database.replace_report(reference_id, original_report):
                    logging.error("SQLite rollback failed.")

                return False

            return True

        except (OSError, json.JSONDecodeError, UnicodeError):
            return False

    def save_report(self, reference_id, ai_result, assessment):
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

        return self.update_report(reference_id, updated_data)


    def save_clarifications(self, reference_id, changes):
        """Save corrected details and invalidate the old assessment."""
        return self.update_report(reference_id, {}, case_changes=changes)

    def delete_report(self, reference_id):
        """Delete a report from SQLite, then its JSON copy and photos."""
        if not isinstance(reference_id, str) or not reference_id.strip():
            return False

        if "/" in reference_id or "\\" in reference_id:
            return False

        if reference_id in (".", ".."):
            return False

        if not self.database_ready:
            return False

        existing_reports = self.database.load_reports()

        if existing_reports is None:
            return False

        original_report = None

        for existing_report in existing_reports:
            if existing_report.get("reference_id") == reference_id:
                original_report = existing_report
                break

        if original_report is None:
            return False

        if not self.database.delete_report(reference_id):
            return False

        # The JSON copy must go too: a leftover file would be imported
        # again by migrate_reports() the next time the application starts.
        if not self.storage.delete_report(reference_id):
            # Restore the SQLite row so both stores stay consistent.
            if not self.database.create_report(original_report):
                logging.error("SQLite rollback failed.")

            return False

        return True
