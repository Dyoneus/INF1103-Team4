import sqlite3
from pathlib import Path
import json

class DatabaseManager:
    def __init__(self, database_path = "data/safereport.db"):
        self.database_path = database_path

    def initialize_database(self):
        try:
            Path(self.database_path).parent.mkdir(
                parents= True, exist_ok= True
            )
            with sqlite3.connect(self.database_path) as connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS reports (
                        reference_id TEXT PRIMARY KEY,
                        report_data TEXT NOT NULL
                    )
                """)
            return True

        except(sqlite3.Error, OSError) as error:
            print("Database initialization failed:", error)
            return False


    def create_report(self, report):
        try:
            reference_id = report["reference_id"]
            report_data = json.dumps(report)

            with sqlite3.connect(self.database_path) as connection:
                connection.execute("""
                    INSERT INTO reports (reference_id, report_data)
                    VALUES (?, ?)
                """, (reference_id, report_data))
            return True

        except(KeyError, TypeError, ValueError, sqlite3.Error) as error:
            print("Failed to create report:", error)
            return False


    def load_reports(self):
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.execute("""
                    SELECT report_data FROM reports
                """)
                rows = cursor.fetchall()

            reports = []

            for row in rows:
                report = json.loads(row[0])
                reports.append(report)

            return reports
        
        except(sqlite3.Error, json.JSONDecodeError, TypeError) as error:
            print("Failed to load reports:", error)
            return None


    def update_report(self, reference_id, updated_data):
        try:
            if not isinstance(updated_data, dict):
                return False

            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.execute("""
                    SELECT report_data FROM reports
                    WHERE reference_id = ?
                """, (reference_id,))

                row = cursor.fetchone()

                if row is None:
                    return False

                report = json.loads(row[0])
                report.update(updated_data)

                if report.get("reference_id") != reference_id:
                    return False

                connection.execute("""
                    UPDATE reports
                    SET report_data = ?
                    WHERE reference_id = ?
                """, (json.dumps(report), reference_id))

            return True

        except (sqlite3.Error, json.JSONDecodeError, TypeError, ValueError) as error:
            print("Failed to update report:", error)
            return False

    
    def delete_report(self, reference_id):
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.execute("""
                    DELETE FROM reports
                    WHERE reference_id = ?
                """, (reference_id,))

                if cursor.rowcount == 0:
                    return False

            return True

        except (sqlite3.Error, TypeError, ValueError) as error:
            print("Failed to delete report:", error)
            return False


    def filter_by_status(self, status):
        try:
            reports = self.load_reports()

            if reports is None:
                return None

            filtered_reports = []

            for report in reports:
                assessment =report.get("assessment", {})

                if assessment.get("status") == status:
                    filtered_reports.append(report)

            return filtered_reports

        except(AttributeError, TypeError) as error:
            print("Failed to filter reports:", error)
            return None
        