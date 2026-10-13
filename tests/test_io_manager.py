from io_manager import validate_report_text
import io_manager

def test_display_assessment_result(capsys):
    assessment = {"status": "NEEDS_CLARIFICATION"}

    io_manager.display_assessment_result(assessment)

    output = capsys.readouterr().out

    assert "Status: Needs clarification" in output

def test_invalid_assessment_result(capsys):
    assessment = {"status": "UNKNOWN"}

    io_manager.display_assessment_result(assessment)

    output = capsys.readouterr().out

    assert "Assessment result unavailable." in output
    
def test_get_report_text_reprompts_for_blank_input(monkeypatch, capsys):
    responses = ["", "   ", "Loose wire."]

    def fake_input(prompt):
        return responses.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)

    result = io_manager.get_report_text()

    assert result == "Loose wire."
    assert responses == []

    output = capsys.readouterr().out
    assert output.count("Description cannot be empty.") == 2

def test_blank_description():
    assert validate_report_text("", 2000) == ["EMPTY_DESCRIPTION"]
    assert validate_report_text("   ", 2000) == ["EMPTY_DESCRIPTION"]

def test_short_description_is_accepted():
    assert validate_report_text("Loose wire.", 2000) == []

def test_description_length_boundary():
    assert validate_report_text("abcde", 5) == []
    assert validate_report_text("abcdef", 5) == [
        "DESCRIPTION_TOO_LONG"
    ]

def test_surrounding_spaces_are_ignored():
    assert validate_report_text("  abcde  ", 5) == []

def test_display_clarification_questions(capsys):
    codes = ["CLARIFY_LOCATION", "ADD_TIME"]

    io_manager.display_clarification_questions(codes)

    output = capsys.readouterr().out

    assert "more specific location" in output
    assert "Approximately what time" in output

def test_quota_error_display(capsys):
    io_manager.display_processing_error("QUOTA_EXHAUSTED")

    output = capsys.readouterr().out

    assert "AI usage limit reached" in output
    assert "The report was not assessed" in output


def test_save_error_display(capsys):
    io_manager.display_processing_error("SAVE_FAILED")

    output = capsys.readouterr().out

    assert "The report could not be saved" in output
    assert "The report was not assessed" not in output


def test_unknown_error_display(capsys):
    io_manager.display_processing_error("UNKNOWN")

    output = capsys.readouterr().out

    assert "An unexpected error occurred" in output