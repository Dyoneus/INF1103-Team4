"""Behaviour checks for the procedural cleanup."""

from itertools import product

import constants
import data_manager
import io_manager
import logic_manager
import main


def test_all_readiness_combinations():
    for values in product(*constants.ALLOWED_VALUES.values()):
        fields = dict(zip(constants.EXTRACTED_FIELDS, values))
        issue, location, date, time, category = values
        if issue == "UNCLEAR" or location == "MISSING":
            expected = "INCOMPLETE"
        elif location == "VAGUE" or date == "MISSING" or time == "MISSING":
            expected = "NEEDS_CLARIFICATION"
        else:
            expected = "READY_FOR_REVIEW"
        codes = []
        if issue == "UNCLEAR":
            codes.append("CLARIFY_OBSERVATION")
        if location == "MISSING":
            codes.append("ADD_LOCATION")
        elif location == "VAGUE":
            codes.append("CLARIFY_LOCATION")
        if date == "MISSING":
            codes.append("ADD_DATE")
        if time == "MISSING":
            codes.append("ADD_TIME")
        assert logic_manager.determine_report_status(fields) == {
            "status": expected, "clarification_codes": codes
        }
    for invalid in (None, [], {}, {"error": "offline"}):
        assert logic_manager.determine_report_status(invalid) == {
            "status": "AI_FAILED", "clarification_codes": []
        }


def test_creation_and_loading_share_report_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "REPORTS_DIR", tmp_path / "reports")
    path = data_manager.create_report({
        "case_details": {"description": "Exposed cable", "photos": []},
        "reporter": {"name": "Test User"},
    })
    assert path.parent == constants.REPORTS_DIR
    assert data_manager.load_reports()[0]["reference_id"] == path.stem


def test_questions_print_once_before_reassessment(monkeypatch, capsys):
    fields = {
        "issue_clarity": "CLEAR", "location_quality": "ADEQUATE",
        "date_quality": "EXACT", "time_quality": "EXACT",
        "safety_category": "ELECTRICAL",
    }
    responses = iter([{**fields, "location_quality": "VAGUE"}, fields])
    monkeypatch.setattr(main.ai_manager, "get_client", lambda: None)
    monkeypatch.setattr(main.ai_manager, "analyze_incident", lambda *args: next(responses))
    monkeypatch.setattr(data_manager, "save_report", lambda *args: True)
    monkeypatch.setattr(data_manager, "save_clarifications", lambda *args: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "Block 30, third floor")
    report = {"case_details": {"description": "Sparks from a cable"}}
    main.assess_report("TEST-001", report)
    output = capsys.readouterr().out
    assert output.count("Please clarify the following:") == 1
    assert output.count("Can you provide a more specific location?") == 1
    assert report["assessment"]["status"] == "READY_FOR_REVIEW"


def test_review_asks_once_per_edit_cycle(monkeypatch):
    answers = iter([True, True, False])
    prompts = []
    edits = []

    def confirm(prompt):
        prompts.append(prompt)
        return next(answers)

    def edit_case():
        edits.append("edit")
        return {"description": f"Edit {len(edits)}"}

    monkeypatch.setattr(io_manager, "ask_yes_no", confirm)
    monkeypatch.setattr(io_manager, "ask_choice", lambda *args: "Case details")
    monkeypatch.setattr(io_manager, "collect_case_details", edit_case)
    report = {"case_details": {}, "reporter": {}}
    result = io_manager.review_report_before_submission(report)
    assert len(edits) == 2
    assert len(prompts) == 3
    assert result["case_details"]["description"] == "Edit 2"
