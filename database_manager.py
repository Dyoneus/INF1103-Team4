import sqlite3
from pathlib import Path

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