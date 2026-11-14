from datetime import datetime

import pytest

from validators import (
    ContactNumberValidator, EmailValidator, IncidentDateTimeValidator,
    NricValidator, PhotoPathValidator, RequiredTextValidator,
)


# ---------- RequiredTextValidator ----------

@pytest.fixture
def short_text():
    return RequiredTextValidator(5, "EMPTY_DESCRIPTION", "DESCRIPTION_TOO_LONG")


@pytest.mark.parametrize("text", ["", "   "])
def test_blank_text_is_rejected(short_text, text):
    assert short_text.validate(text) == ["EMPTY_DESCRIPTION"]


def test_text_length_boundary(short_text):
    assert short_text.validate("abcde") == []
    assert short_text.validate("abcdef") == ["DESCRIPTION_TOO_LONG"]


def test_surrounding_spaces_are_ignored(short_text):
    assert short_text.validate("  abcde  ") == []
    assert short_text.clean("  abcde  ") == "abcde"


# ---------- EmailValidator ----------

def test_valid_email_is_cleaned_to_lowercase():
    validator = EmailValidator()
    assert validator.validate(" Ali@Mail.COM ") == []
    assert validator.clean(" Ali@Mail.COM ") == "ali@mail.com"


@pytest.mark.parametrize("text, code", [
    ("", "EMPTY_EMAIL"),
    ("ali", "INVALID_EMAIL"),
    ("ali@mail", "INVALID_EMAIL"),
    ("ali@@mail.com", "INVALID_EMAIL"),
])
def test_invalid_email(text, code):
    assert EmailValidator().validate(text) == [code]


# ---------- NricValidator ----------

@pytest.mark.parametrize("nric", ["S1234567D", "T1234567J", "F1234567N", "G1234567X", "M1234567K"])
def test_valid_nric_and_fin(nric):
    assert NricValidator().validate(nric) == []


def test_nric_is_cleaned_to_uppercase():
    assert NricValidator().validate(" s1234567d ") == []
    assert NricValidator().clean(" s1234567d ") == "S1234567D"


@pytest.mark.parametrize("text, code", [
    ("", "EMPTY_NRIC"),
    ("S123456D", "INVALID_NRIC_FORMAT"),
    ("A1234567D", "INVALID_NRIC_FORMAT"),
    ("S1234567A", "INVALID_NRIC_CHECKSUM"),
])
def test_invalid_nric(text, code):
    assert NricValidator().validate(text) == [code]


# ---------- ContactNumberValidator ----------

@pytest.mark.parametrize("text", ["91234567", "+65 9123 4567", "6591234567", "8123-4567"])
def test_valid_mobile_numbers(text):
    validator = ContactNumberValidator("Mobile")
    assert validator.validate(text) == []
    assert len(validator.clean(text)) == 8


def test_plus65_prefix_is_removed():
    assert ContactNumberValidator("Mobile").clean("+65 9123-4567") == "91234567"


@pytest.mark.parametrize("contact_type, text", [
    ("Mobile", "61234567"),
    ("Home", "91234567"),
    ("Office", "81234567"),
])
def test_number_must_match_contact_type(contact_type, text):
    assert ContactNumberValidator(contact_type).validate(text) == ["WRONG_NUMBER_TYPE"]


@pytest.mark.parametrize("text, code", [
    ("", "EMPTY_CONTACT_NUMBER"),
    ("1234", "INVALID_CONTACT_NUMBER"),
    ("9123abcd", "INVALID_CONTACT_NUMBER"),
])
def test_invalid_contact_number(text, code):
    assert ContactNumberValidator("Mobile").validate(text) == [code]


# ---------- IncidentDateTimeValidator ----------

@pytest.fixture
def datetime_validator():
    """Validator whose 'now' is fixed, so the tests never depend on the real date."""
    return IncidentDateTimeValidator(
        "%Y-%m-%d %H:%M",
        clock=lambda: datetime(2026, 11, 12, 12, 0),
    )


def test_past_datetime_is_accepted_and_stored_as_iso(datetime_validator):
    assert datetime_validator.validate("2026-10-09 14:30") == []
    assert datetime_validator.clean("2026-10-09 14:30") == "2026-10-09T14:30"


def test_current_minute_is_accepted(datetime_validator):
    assert datetime_validator.validate("2026-11-12 12:00") == []


@pytest.mark.parametrize("text, code", [
    ("", "EMPTY_DATETIME"),
    ("09/10/2026 14:30", "INVALID_DATETIME"),
    ("2026-02-30 10:00", "INVALID_DATETIME"),
    ("2026-11-12 12:01", "FUTURE_DATETIME"),
])
def test_invalid_datetime(datetime_validator, text, code):
    assert datetime_validator.validate(text) == [code]


# ---------- PhotoPathValidator ----------

@pytest.fixture
def photo_validator():
    return PhotoPathValidator({".jpg", ".jpeg", ".png"})


def test_existing_photo_is_accepted(photo_validator, tmp_path):
    photo = tmp_path / "hazard.JPG"
    photo.write_bytes(b"fake image")
    assert photo_validator.validate(f'"{photo}"') == []          # quotes from drag-and-drop
    assert photo_validator.clean(f'"{photo}"') == str(photo.resolve())


def test_missing_photo_is_rejected(photo_validator, tmp_path):
    assert photo_validator.validate(str(tmp_path / "nope.jpg")) == ["PHOTO_NOT_FOUND"]


def test_wrong_file_type_is_rejected(photo_validator, tmp_path):
    document = tmp_path / "notes.txt"
    document.write_text("not a photo")
    assert photo_validator.validate(str(document)) == ["PHOTO_BAD_TYPE"]
