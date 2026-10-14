"""Procedural workflow tests using temporary records and mocked AI calls."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import ai_manager
import data_manager
import io_manager
import main


FIELDS = {
    "issue_clarity": "CLEAR", "location_quality": "ADEQUATE",
    "date_quality": "EXACT", "time_quality": "EXACT",
    "safety_category": "ELECTRICAL",
}


def saved_report(tmp_path, monkeypatch, status, codes=None):
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
    return path, report


def answer_with(monkeypatch, answers):
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))


def successful_ai(monkeypatch):
    monkeypatch.setattr(ai_manager, "get_client", lambda: None)
    monkeypatch.setattr(ai_manager, "analyze_incident", lambda *args: FIELDS)


def test_retry_updates_original_record(tmp_path, monkeypatch):
    path, original = saved_report(tmp_path, monkeypatch, "AI_FAILED")
    answer_with(monkeypatch, ["TEST-001"])
    monkeypatch.setattr(ai_manager, "get_client", lambda: None)

    def analyze(client, details, photos):
        assert "reporter" not in details
        assert "photos" not in details
        assert photos == []  # Consent is still honoured during retries.
        return FIELDS

    monkeypatch.setattr(ai_manager, "analyze_incident", analyze)
    main.retry_failed_report()
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["assessment"]["status"] == "READY_FOR_REVIEW"
    assert result["ai_result"]["reference_id"] == original["reference_id"]
    for field in ("case_details", "reporter", "submitted_at"):
        assert result[field] == original[field]
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_clarification_saves_before_ai_and_reassesses(tmp_path, monkeypatch):
    path, original = saved_report(
        tmp_path, monkeypatch, "NEEDS_CLARIFICATION", ["CLARIFY_LOCATION"]
    )
    answer_with(monkeypatch, ["1", "Block 30, third floor, north stairwell"])
    monkeypatch.setattr(ai_manager, "get_client", lambda: None)

    def analyze(client, details, photos):
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["assessment"]["status"] == "AI_FAILED"
        assert stored["ai_result"] is None
        assert stored["case_details"]["workplace_location"] == details["workplace_location"]
        assert "north stairwell" in details["workplace_location"]
        return FIELDS

    monkeypatch.setattr(ai_manager, "analyze_incident", analyze)
    main.clarify_report()
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["assessment"] == {"status": "READY_FOR_REVIEW", "clarification_codes": []}
    assert result["reporter"] == original["reporter"]
    assert result["case_details"]["photos"] == original["case_details"]["photos"]
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_corrections_survive_ai_failure_and_can_be_retried(tmp_path, monkeypatch):
    path, _ = saved_report(tmp_path, monkeypatch, "INCOMPLETE", ["CLARIFY_OBSERVATION"])
    answer_with(monkeypatch, ["1", "Sparks are coming from an exposed cable."])

    def missing_client():
        raise RuntimeError("Missing API key")

    monkeypatch.setattr(ai_manager, "get_client", missing_client)
    main.clarify_report()
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["case_details"]["description"].startswith("Sparks")
    assert result["assessment"]["status"] == "AI_FAILED"
    assert data_manager.get_failed_ai_reports()[0]["reference_id"] == "TEST-001"
    successful_ai(monkeypatch)
    answer_with(monkeypatch, ["1"])
    main.retry_failed_report()
    assert json.loads(path.read_text(encoding="utf-8"))["assessment"]["status"] == "READY_FOR_REVIEW"


def test_clarification_cancel_does_not_save_partial_answers(tmp_path, monkeypatch):
    path, _ = saved_report(tmp_path, monkeypatch, "INCOMPLETE", ["CLARIFY_OBSERVATION", "ADD_LOCATION"])
    before = path.read_bytes()
    responses = iter(["1", "A clearer description"])

    def interrupted_input(prompt):
        value = next(responses, None)
        if value is None:
            raise KeyboardInterrupt
        return value

    monkeypatch.setattr("builtins.input", interrupted_input)
    main.clarify_report()
    assert path.read_bytes() == before


def test_failed_correction_save_keeps_original_and_skips_ai(tmp_path, monkeypatch):
    path, _ = saved_report(tmp_path, monkeypatch, "NEEDS_CLARIFICATION", ["CLARIFY_LOCATION"])
    before = path.read_bytes()
    answer_with(monkeypatch, ["1", "Block 30"])

    def cannot_replace(*args):
        raise OSError("Disk unavailable")

    def unexpected_ai():
        pytest.fail("AI must not run before corrections are saved")

    monkeypatch.setattr(data_manager.os, "replace", cannot_replace)
    monkeypatch.setattr(ai_manager, "get_client", unexpected_ai)
    main.clarify_report()
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_clarification_validates_and_collects_datetime_once(monkeypatch):
    report = {"case_details": {}, "assessment": {"clarification_codes": ["ADD_DATE", "ADD_TIME"]}}
    answer_with(monkeypatch, ["bad date", "2020-01-02 09:30"])
    assert io_manager.collect_clarifications(report) == {"incident_datetime": "2020-01-02T09:30"}


@pytest.mark.parametrize("choice", ["0", "TEST-001"])
def test_select_report_by_reference_or_cancel(monkeypatch, choice):
    report = {"reference_id": "TEST-001"}
    answer_with(monkeypatch, ["invalid", choice])
    assert io_manager.select_saved_report([report]) == (None if choice == "0" else report)


def test_corrections_cannot_change_protected_fields(tmp_path, monkeypatch):
    path, _ = saved_report(tmp_path, monkeypatch, "INCOMPLETE")
    before = path.read_bytes()
    assert not data_manager.save_clarifications("TEST-001", {"photos": []})
    assert not data_manager.save_clarifications("../TEST-001", {"description": "Test"})
    assert path.read_bytes() == before


def test_menu_dispatches_saved_workflows(monkeypatch):
    answer_with(monkeypatch, ["2", "3", "0"])
    monkeypatch.setattr(data_manager, "load_reports", lambda: [])
    calls = []
    monkeypatch.setattr(main, "retry_failed_report", lambda: calls.append("retry"))
    monkeypatch.setattr(main, "clarify_report", lambda: calls.append("clarify"))
    main.run()
    assert calls == ["retry", "clarify"]


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
