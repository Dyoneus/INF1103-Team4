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