"""Tests for ConsolePrompter working with the Validator interface."""

import pytest

import io_manager
from io_manager import ConsolePrompter
from validators import (
    Validator, RequiredTextValidator, EmailValidator, NricValidator,
    ContactNumberValidator, IncidentDateTimeValidator,
)


def make_prompter(answers):
    answers = list(answers)
    shown = []
    prompter = ConsolePrompter(
        io_manager.ERROR_MESSAGES,
        input_fn=lambda prompt: answers.pop(0),
        output_fn=lambda text="": shown.append(text),
    )
    return prompter, answers, shown


class PostalCodeValidator(Validator):
    """A validator the I/O Manager has never seen, to show any subclass can be used."""

    def validate(self, text):
        return [] if text.strip().isdigit() and len(text.strip()) == 6 else ["INVALID_POSTAL_CODE"]


def test_ask_until_valid_reprompts_then_returns_cleaned_value():
    prompter, remaining, shown = make_prompter(["not-an-email", "  Ali@Mail.COM "])

    assert prompter.ask_until_valid("Email: ", EmailValidator()) == "ali@mail.com"
    assert remaining == []
    assert any("valid email" in line for line in shown)


@pytest.mark.parametrize("validator, bad, good, expected", [
    (RequiredTextValidator(10, "EMPTY_NAME", "NAME_TOO_LONG"), "   ", " Ali ", "Ali"),
    (EmailValidator(), "ali@", "ALI@MAIL.COM", "ali@mail.com"),
    (NricValidator(), "S1234567A", "s1234567d", "S1234567D"),
    (ContactNumberValidator("Office"), "91234567", "6123 4567", "61234567"),
    (IncidentDateTimeValidator("%Y-%m-%d %H:%M"), "yesterday", "2020-01-02 09:30", "2020-01-02T09:30"),
    (PostalCodeValidator(), "12AB", " 123456 ", "123456"),
])
def test_ask_until_valid_works_with_any_validator(validator, bad, good, expected):
    """LSP: every Validator subclass can be substituted without changing ask_until_valid."""
    prompter, remaining, _ = make_prompter([bad, good])

    assert prompter.ask_until_valid("Value: ", validator) == expected
    assert remaining == []


def test_optional_prompt_returns_none_for_blank_answer():
    prompter, _, _ = make_prompter([""])

    assert prompter.ask_until_valid("Optional: ", EmailValidator(), optional=True) is None


def test_unknown_error_code_shows_generic_message():
    prompter, _, shown = make_prompter(["12AB", "123456"])

    prompter.ask_until_valid("Postal code: ", PostalCodeValidator())

    assert "Invalid input." in shown


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
