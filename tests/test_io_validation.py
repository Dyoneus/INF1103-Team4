import io_manager
from validators import EmailValidator


def fake_inputs(monkeypatch, answers):
    answers = list(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": answers.pop(0))
    return answers


def test_ask_until_valid_reprompts_then_returns_cleaned_value(monkeypatch, capsys):
    remaining = fake_inputs(monkeypatch, ["not-an-email", "  Ali@Mail.COM "])

    result = io_manager.ask_until_valid("Email: ", EmailValidator())

    assert result == "ali@mail.com"
    assert remaining == []
    assert "valid email" in capsys.readouterr().out


def test_collect_contact_details_returns_cleaned_values(monkeypatch, capsys):
    fake_inputs(monkeypatch, [
        "Ali",                                  # name
        "Ali@Mail.com", "ali@mail.com",         # email + confirm
        "s1234567a", "s1234567d",               # bad checksum, then valid NRIC
        "2",                                    # contact type: Mobile
        "61234567", "+65 9123-4567",            # landline rejected, then mobile
    ])

    details = io_manager.collect_contact_details()

    assert details == {
        "name": "Ali",
        "email": "ali@mail.com",
        "nric_fin": "S1234567D",
        "contact_type": "Mobile",
        "contact_number": "91234567",
    }
    output = capsys.readouterr().out
    assert "check the last letter" in output
    assert "doesn't match the contact type" in output


def test_every_error_code_has_a_message():
    """Every code a validator can return must have a user-facing message."""
    codes = {
        "EMPTY_DESCRIPTION", "DESCRIPTION_TOO_LONG", "EMPTY_LOCATION", "LOCATION_TOO_LONG",
        "EMPTY_WORKPLACE_NAME", "EMPTY_NAME", "NAME_TOO_LONG", "EMPTY_EMAIL", "INVALID_EMAIL",
        "EMPTY_NRIC", "INVALID_NRIC_FORMAT", "INVALID_NRIC_CHECKSUM",
        "EMPTY_CONTACT_NUMBER", "INVALID_CONTACT_NUMBER", "WRONG_NUMBER_TYPE",
        "EMPTY_DATETIME", "INVALID_DATETIME", "FUTURE_DATETIME",
        "PHOTO_NOT_FOUND", "PHOTO_BAD_TYPE",
    }
    assert codes <= set(io_manager.ERROR_MESSAGES)
