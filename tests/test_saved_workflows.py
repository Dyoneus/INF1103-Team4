"""Application workflow tests using temporary records and mocked AI calls."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import ai_manager
import data_manager
import io_manager
import main

from database_manager import DatabaseManager
import report_store

FIELDS = {
    "issue_clarity": "CLEAR", "location_quality": "ADEQUATE",
    "date_quality": "EXACT", "time_quality": "EXACT",
    "safety_category": "ELECTRICAL",
}

@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    database = DatabaseManager(tmp_path / "safereport.db")
    monkeypatch.setattr(data_manager, "REPORTS_DIR", tmp_path)
    manager = data_manager.DataManager(database)
    assert manager.database_ready
    return manager


def test_database_manager_uses_configured_database_path(tmp_path, monkeypatch):
    database_path = tmp_path / "persistent" / "safereport.db"
    monkeypatch.setenv("SAFEREPORT_DATABASE_PATH", str(database_path))

    database = DatabaseManager()

    assert database.initialize_database()
    assert database_path.is_file()
    report = {"reference_id": "PERSISTED-001"}
    assert database.create_report(report)
    assert DatabaseManager().load_reports() == [report]


@pytest.fixture
def application(isolated_database):
    return main.SafeReportApplication(
        io_manager.IOManager(),
        ai_manager.AIManager(),
        main.logic_manager.LogicManager(),
        isolated_database,
    )

def saved_report(tmp_path, monkeypatch, isolated_database, status, codes=None, in_database=True):
    monkeypatch.setattr(data_manager, "REPORTS_DIR", tmp_path)
    report = {
        "reference_id": "TEST-001", "submitted_at": "2026-01-01T12:00:00",
        "case_details": {
            "description": "An exposed cable.",
            "workplace_location": "Warehouse",
            "incident_datetime": "2026-01-01T11:00",
            "photos": ["reports/photos/TEST-001/photo_1.png"],
            "consent_for_image_use": False,
        },
        "reporter": {"name": "Test User"},
        "assessment": {"status": status, "clarification_codes": codes or []},
    }
    path = tmp_path / "TEST-001.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    if in_database:
        # load_reports() reads SQLite only, so seed the database as well.
        assert isolated_database.database.create_report(report)
    return path, report


def answer_with(monkeypatch, answers):
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))


def successful_ai(monkeypatch):
    monkeypatch.setattr(ai_manager.AIManager, "ensure_ready", lambda self: None)
    monkeypatch.setattr(ai_manager.AIManager, "analyze_incident", lambda *args: FIELDS)


def test_retry_updates_original_record(tmp_path, monkeypatch, application, isolated_database):
    path, original = saved_report(tmp_path, monkeypatch, isolated_database, "AI_FAILED")
    answer_with(monkeypatch, ["TEST-001"])
    monkeypatch.setattr(ai_manager.AIManager, "ensure_ready", lambda self: None)

    def analyze(self, details, photos):
        assert "reporter" not in details
        assert "photos" not in details
        assert photos == []  # Consent is still honoured during retries.
        return FIELDS

    monkeypatch.setattr(ai_manager.AIManager, "analyze_incident", analyze)
    application.retry_failed_report()
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["assessment"]["status"] == "READY_FOR_REVIEW"
    assert result["ai_result"]["reference_id"] == original["reference_id"]
    for field in ("case_details", "reporter", "submitted_at"):
        assert result[field] == original[field]
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert isolated_database.database.load_reports() == [result]


def test_clarification_saves_before_ai_and_reassesses(tmp_path, monkeypatch, application, isolated_database):
    path, original = saved_report(
        tmp_path, monkeypatch, isolated_database, "NEEDS_CLARIFICATION", ["CLARIFY_LOCATION"]
    )
    answer_with(monkeypatch, ["1", "Block 30, third floor, north stairwell"])
    monkeypatch.setattr(ai_manager.AIManager, "ensure_ready", lambda self: None)

    def analyze(self, details, photos):
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["assessment"]["status"] == "AI_FAILED"
        assert stored["ai_result"] is None
        assert stored["case_details"]["workplace_location"] == details["workplace_location"]
        assert "north stairwell" in details["workplace_location"]
        return FIELDS

    monkeypatch.setattr(ai_manager.AIManager, "analyze_incident", analyze)
    application.clarify_report()
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["assessment"] == {"status": "READY_FOR_REVIEW", "clarification_codes": []}
    assert result["reporter"] == original["reporter"]
    assert result["case_details"]["photos"] == original["case_details"]["photos"]
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert isolated_database.database.load_reports() == [result]


def test_corrections_survive_ai_failure_and_can_be_retried(tmp_path, monkeypatch, application, isolated_database):
    path, _ = saved_report(tmp_path, monkeypatch, isolated_database, "INCOMPLETE", ["CLARIFY_OBSERVATION"])
    answer_with(monkeypatch, ["1", "Sparks are coming from an exposed cable."])

    def missing_client(self):
        raise RuntimeError("Missing API key")

    monkeypatch.setattr(ai_manager.AIManager, "ensure_ready", missing_client)
    application.clarify_report()
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["case_details"]["description"].startswith("Sparks")
    assert result["assessment"]["status"] == "AI_FAILED"
    assert isolated_database.get_failed_ai_reports()[0]["reference_id"] == "TEST-001"
    successful_ai(monkeypatch)
    answer_with(monkeypatch, ["1"])
    application.retry_failed_report()
    assert json.loads(path.read_text(encoding="utf-8"))["assessment"]["status"] == "READY_FOR_REVIEW"


def test_clarification_cancel_does_not_save_partial_answers(tmp_path, monkeypatch, application, isolated_database):
    path, _ = saved_report(tmp_path, monkeypatch, isolated_database, "INCOMPLETE", ["CLARIFY_OBSERVATION", "ADD_LOCATION"])
    before = path.read_bytes()
    responses = iter(["1", "A clearer description"])

    def interrupted_input(prompt):
        value = next(responses, None)
        if value is None:
            raise KeyboardInterrupt
        return value

    monkeypatch.setattr("builtins.input", interrupted_input)
    application.clarify_report()
    assert path.read_bytes() == before


def test_failed_correction_save_keeps_original_and_skips_ai(tmp_path, monkeypatch, application, isolated_database):
    path, _ = saved_report(tmp_path, monkeypatch, isolated_database, "NEEDS_CLARIFICATION", ["CLARIFY_LOCATION"])
    before = path.read_bytes()
    answer_with(monkeypatch, ["1", "Block 30"])

    def cannot_replace(*args):
        raise OSError("Disk unavailable")

    def unexpected_ai(self):
        pytest.fail("AI must not run before corrections are saved")

    monkeypatch.setattr(report_store.os, "replace", cannot_replace)
    monkeypatch.setattr(ai_manager.AIManager, "ensure_ready", unexpected_ai)
    application.clarify_report()
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))
    assert isolated_database.load_reports()[0]["case_details"]["workplace_location"] == "Warehouse"

def test_clarification_validates_and_collects_datetime_once(monkeypatch):
    report = {"case_details": {}, "assessment": {"clarification_codes": ["ADD_DATE", "ADD_TIME"]}}
    answer_with(monkeypatch, ["bad date", "2020-01-02 09:30"])
    assert io_manager.IOManager().collect_clarifications(report) == {"incident_datetime": "2020-01-02T09:30"}


@pytest.mark.parametrize("choice", ["0", "TEST-001"])
def test_select_report_by_reference_or_cancel(monkeypatch, choice):
    report = {"reference_id": "TEST-001"}
    answer_with(monkeypatch, ["invalid", choice])
    assert io_manager.IOManager().select_saved_report([report]) == (None if choice == "0" else report)


def test_corrections_cannot_change_protected_fields(tmp_path, monkeypatch, isolated_database):
    path, _ = saved_report(tmp_path, monkeypatch, isolated_database, "INCOMPLETE")
    before = path.read_bytes()
    assert not isolated_database.save_clarifications("TEST-001", {"photos": []})
    assert not isolated_database.save_clarifications("../TEST-001", {"description": "Test"})
    assert path.read_bytes() == before

def test_menu_dispatches_saved_workflows(monkeypatch):
    from unittest.mock import Mock

    answer_with(monkeypatch, ["2", "3", "0"])
    data = Mock(spec=data_manager.DataManager)
    data.load_reports.return_value = []
    data_class = Mock(return_value=data)
    monkeypatch.setattr(data_manager, "DataManager", data_class)
    calls = []

    monkeypatch.setattr(
        main.SafeReportApplication,
        "retry_failed_report",
        lambda self: calls.append("retry"),
    )
    monkeypatch.setattr(
        main.SafeReportApplication,
        "clarify_report",
        lambda self: calls.append("clarify"),
    )

    main.SafeReportApplication.main()

    assert calls == ["retry", "clarify"]
    data_class.assert_called_once_with()
    data.load_reports.assert_called_once_with()


@pytest.mark.parametrize("script", ["main.py"])
def test_script_entrypoints_open_menu(script, tmp_path):
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(project / script)], cwd=tmp_path,
        input="0\n", capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "2. Retry a failed assessment" in result.stdout
    assert "3. Clarify and reassess" in result.stdout
    assert "4. Delete a saved report" in result.stdout

def test_legacy_json_is_migrated_without_duplicates(tmp_path, monkeypatch, isolated_database):
    _, original = saved_report(
        tmp_path, monkeypatch, isolated_database, "AI_FAILED", in_database=False
    )

    assert isolated_database.load_reports() == []
    assert isolated_database.migrate_reports()
    assert isolated_database.migrate_reports()
    assert isolated_database.load_reports() == [original]
    assert isolated_database.database.load_reports() == [original]


def test_invalid_legacy_json_fails_migration_but_not_loading(tmp_path, isolated_database):
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")

    assert not isolated_database.migrate_reports()
    assert isolated_database.load_reports() == []


def test_legacy_json_is_imported_once_at_startup(tmp_path, monkeypatch, isolated_database):
    _, original = saved_report(
        tmp_path, monkeypatch, isolated_database, "AI_FAILED", in_database=False
    )
    database = DatabaseManager(tmp_path / "startup.db")

    manager = data_manager.DataManager(database)

    assert manager.legacy_import_ok
    assert manager.load_reports() == [original]


def test_unavailable_database_reports_load_failure(isolated_database):
    isolated_database._database_ready = False

    assert isolated_database.load_reports() is None


def test_unavailable_database_raises_on_create(isolated_database):
    isolated_database._database_ready = False

    with pytest.raises(OSError):
        isolated_database.create_report({})

def test_data_manager_storage_dependency_injection(tmp_path, monkeypatch):
    database = DatabaseManager(tmp_path / "test.db")
    storage = report_store.ReportStorage(tmp_path)

    monkeypatch.setattr(data_manager, "REPORTS_DIR", tmp_path)

    manager = data_manager.DataManager(
        database=database,
        storage=storage
    )

    assert manager.database is database
    assert manager.storage is storage
    assert manager.database_ready is True


# Deleting a saved report

def add_photo_folder(tmp_path):
    photo = tmp_path / "photos" / "TEST-001" / "photo_1.png"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"photo")
    return photo


def test_delete_removes_database_row_json_and_photos(
    tmp_path, monkeypatch, application, isolated_database
):
    path, _ = saved_report(tmp_path, monkeypatch, isolated_database, "READY_FOR_REVIEW")
    photo = add_photo_folder(tmp_path)
    answer_with(monkeypatch, ["TEST-001", "y"])

    application.delete_report()

    assert isolated_database.load_reports() == []
    assert not path.exists()
    assert not photo.parent.exists()
    # A fresh start must not import the report again from a leftover JSON file.
    assert data_manager.DataManager(isolated_database.database).load_reports() == []


def test_delete_declined_keeps_the_report(
    tmp_path, monkeypatch, application, isolated_database
):
    path, original = saved_report(tmp_path, monkeypatch, isolated_database, "READY_FOR_REVIEW")
    photo = add_photo_folder(tmp_path)
    answer_with(monkeypatch, ["TEST-001", "n"])

    application.delete_report()

    assert isolated_database.load_reports() == [original]
    assert path.is_file() and photo.is_file()


@pytest.mark.parametrize("reference_id", ["MISSING-001", "", "../TEST-001", "..", None])
def test_delete_rejects_unknown_or_unsafe_reference_ids(
    tmp_path, monkeypatch, isolated_database, reference_id
):
    path, original = saved_report(tmp_path, monkeypatch, isolated_database, "READY_FOR_REVIEW")

    assert isolated_database.delete_report(reference_id) is False
    assert isolated_database.load_reports() == [original]
    assert path.is_file()


def test_delete_restores_database_row_when_json_cannot_be_removed(
    tmp_path, monkeypatch, isolated_database
):
    path, original = saved_report(tmp_path, monkeypatch, isolated_database, "READY_FOR_REVIEW")
    monkeypatch.setattr(
        report_store.ReportStorage, "delete_report", lambda self, reference_id: False
    )

    assert isolated_database.delete_report("TEST-001") is False
    assert isolated_database.load_reports() == [original]
    assert path.is_file()


def test_storage_delete_never_leaves_the_photos_folder(tmp_path):
    storage = report_store.ReportStorage(tmp_path)
    keep = tmp_path / "photos" / "KEEP-001" / "photo_1.png"
    keep.parent.mkdir(parents=True)
    keep.write_bytes(b"photo")

    assert storage.delete_report("..") is True
    assert storage.delete_report("MISSING-001") is True
    assert keep.is_file()
