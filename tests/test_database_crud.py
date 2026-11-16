from database_manager import DatabaseManager
import sqlite3

def test_delete_report(tmp_path):
    database = DatabaseManager(tmp_path / "test.db")

    assert database.initialize_database()

    report = {
        "reference_id": "TEST-001",
        "case_details": {
            "workplace_location": "Warehouse"
        },
        "assessment": {
            "status": "READY_FOR_REVIEW"
        }
    }

    assert database.create_report(report)
    assert database.load_reports() == [report]

    assert database.delete_report("TEST-001")
    assert database.load_reports() == []

    assert database.delete_report("TEST-001") is False



def test_filter_by_status(tmp_path):
    database = DatabaseManager(tmp_path / "test.db")

    assert database.initialize_database()

    report1 = {
        "reference_id": "TEST-001",
        "assessment": {"status": "READY_FOR_REVIEW"}
    }

    report2 = {
        "reference_id": "TEST-002",
        "assessment": {"status": "AI_FAILED"}
    }

    assert database.create_report(report1)
    assert database.create_report(report2)

    assert database.filter_by_status("READY_FOR_REVIEW") == [report1]
    assert database.filter_by_status("AI_FAILED") == [report2]
    assert database.filter_by_status("INCOMPLETE") == []


def test_filter_by_location(tmp_path):
    database = DatabaseManager(tmp_path / "test.db")

    assert database.initialize_database()

    report1 = {
        "reference_id": "TEST-001",
        "case_details": {
            "workplace_location": "Warehouse"
        }
    }

    report2 = {
        "reference_id": "TEST-002",
        "case_details": {
            "workplace_location": "Office"
        }
    }

    assert database.create_report(report1)
    assert database.create_report(report2)

    assert database.filter_by_location("Warehouse") == [report1]
    assert database.filter_by_location("Office") == [report2]
    assert database.filter_by_location("Factory") == []


def test_replace_report(tmp_path):
    database = DatabaseManager(tmp_path / "test.db")

    assert database.initialize_database()

    original_report = {
        "reference_id": "TEST-001",
        "assessment": {
            "status": "AI_FAILED"
        }
    }

    updated_report = {
        "reference_id": "TEST-001",
        "assessment": {
            "status": "READY_FOR_REVIEW"
        }
    }

    assert database.create_report(original_report)

    assert database.replace_report("TEST-001", updated_report)
    assert database.load_reports() == [updated_report]

    assert database.replace_report("TEST-999", updated_report) is False
    assert database.replace_report("TEST-001", {
        "reference_id": "TEST-002"
    }) is False

    assert database.load_reports() == [updated_report]


def test_load_reports_with_corrupted_record(tmp_path):
    database = DatabaseManager(tmp_path / "test.db")

    assert database.initialize_database()

    valid_report = {
        "reference_id": "TEST-001",
        "assessment": {"status": "READY_FOR_REVIEW"}
    }

    assert database.create_report(valid_report)

    # Insert a corrupted JSON record directly into SQLite.
    with sqlite3.connect(database.database_path) as connection:
        connection.execute(
            "INSERT INTO reports (reference_id, report_data) VALUES (?, ?)",
            ("BROKEN-001", "{invalid json")
        )

    # A corrupted record should not prevent valid reports from loading.
    assert database.load_reports() == [valid_report]

def test_corrupted_database_file(tmp_path):
    database_path = tmp_path / "corrupted.db"

    database_path.write_bytes(b"This is not a SQLite database")

    database = DatabaseManager(database_path)

    assert database.initialize_database() is False
