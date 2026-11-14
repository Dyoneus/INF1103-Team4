"""Tests for the I/O Manager classes (no real terminal or AI needed)."""

import pytest


VALID_CONTACT_ANSWERS = ["Ali", "ali@mail.com", "ali@mail.com", "S1234567D", "2", "91234567"]


def sample_report():
    return {
        "case_details": {
            "description": "Old description",
            "photos": [],
            "consent_for_image_use": None,
            "workplace_name": "Old workplace",
            "workplace_location": "Old location",
            "incident_datetime": "2026-10-13T10:00",
            "reporter_profile": "Employee of the workplace",
        },
        "reporter": {
            "name": "Jane",
            "email": "jane@example.com",
            "nric_fin": "S1234567D",
            "contact_type": "Mobile",
            "contact_number": "91234567",
        },
    }


# Collecting a new report

def test_collect_report_returns_cleaned_values(make_io):
    io, console = make_io([
        "Loose wire near the pantry.",              # description
        "",                                         # no photos
        "ACME Pte Ltd",                             # workplace name
        "Block 30, level 3",                        # location
        "2026-10-09 14:30",                         # incident date/time
        "1",                                        # profile
        "Ali",                                      # name
        "Ali@Mail.com", "ali@mail.com",             # email + confirm
        "s1234567a", "s1234567d",                   # bad checksum, then valid NRIC
        "2",                                        # contact type: Mobile
        "61234567", "+65 9123-4567",                # landline rejected, then mobile
    ])

    report = io.collect_report()

    assert report == {
        "case_details": {
            "description": "Loose wire near the pantry.",
            "photos": [],
            "consent_for_image_use": None,
            "workplace_name": "ACME Pte Ltd",
            "workplace_location": "Block 30, level 3",
            "incident_datetime": "2026-10-09T14:30",
            "reporter_profile": "Employee of the workplace",
        },
        "reporter": {
            "name": "Ali",
            "email": "ali@mail.com",
            "nric_fin": "S1234567D",
            "contact_type": "Mobile",
            "contact_number": "91234567",
        },
    }
    assert console.remaining == []
    assert "check the last letter" in console.text
    assert "doesn't match the contact type" in console.text


def test_duplicate_photo_is_rejected_and_consent_is_asked(make_io, tmp_path):
    photo = tmp_path / "hazard.jpg"
    photo.write_bytes(b"fake image")
    io, console = make_io([
        "Exposed cable.", str(photo), str(photo), "", "y",
        "ACME", "Block 30", "2026-10-09 14:30", "1",
        *VALID_CONTACT_ANSWERS,
    ])

    report = io.collect_report()

    assert report["case_details"]["photos"] == [str(photo.resolve())]
    assert report["case_details"]["consent_for_image_use"] is True
    assert "You already added that photo." in console.text


@pytest.mark.parametrize("cancel", [KeyboardInterrupt(), EOFError()])
def test_cancelling_part_way_returns_none(make_io, cancel):
    io, console = make_io(["Exposed cable.", "", "ACME", cancel])

    assert io.collect_report() is None
    assert "Report entry cancelled." in console.text


# Reviewing before submission

def test_review_edit_replaces_contact_details(make_io):
    io, console = make_io([
        "y", "2",                                                   # edit contact details
        "Bob", "bob@mail.com", "bob@mail.com", "S1234567D", "2", "81234567",
        "n",                                                        # no further changes
    ])
    report = sample_report()

    result = io.review_report_before_submission(report)

    assert result["reporter"]["name"] == "Bob"
    assert result["reporter"]["contact_number"] == "81234567"
    assert result["case_details"] == sample_report()["case_details"]
    assert console.text.count("Report summary") == 2


def test_ctrl_c_while_editing_keeps_previous_details(make_io):
    """Regression: Ctrl+C part-way through an edit used to crash the app."""
    io, console = make_io(["y", "2", "Bob", KeyboardInterrupt(), "n"])
    report = sample_report()

    result = io.review_report_before_submission(report)

    assert result["reporter"] == sample_report()["reporter"]
    assert "Edit cancelled. Your previous details were kept." in console.text
    assert console.remaining == []


def test_review_submit_option_returns_report_unchanged(make_io):
    io, _ = make_io(["y", "0"])

    assert io.review_report_before_submission(sample_report()) == sample_report()


# Clarifications

def test_clarification_only_asks_for_flagged_fields(make_io):
    io, console = make_io(["Block 30, level 3, near the lift lobby"])
    report = {**sample_report(), "assessment": {"clarification_codes": ["CLARIFY_LOCATION"]}}

    changes = io.collect_clarifications(report)

    assert changes == {"workplace_location": "Block 30, level 3, near the lift lobby"}
    assert "more specific location" in console.text
    assert "Current location: Old location" in console.text
    assert console.remaining == []


def test_clarified_description_reprompts_for_blank_input(make_io):
    io, console = make_io(["", "   ", "Loose wire."])
    report = {**sample_report(), "assessment": {"clarification_codes": ["CLARIFY_OBSERVATION"]}}

    assert io.collect_clarifications(report) == {"description": "Loose wire."}
    assert console.text.count("Description cannot be empty.") == 2


def test_cancelling_clarification_returns_none_and_does_not_change_report(make_io):
    io, console = make_io(["Block 30", KeyboardInterrupt()])
    report = {**sample_report(), "assessment": {"clarification_codes": ["ADD_LOCATION", "ADD_DATE"]}}

    assert io.collect_clarifications(report) is None
    assert report["case_details"]["workplace_location"] == "Old location"
    assert "Clarification cancelled. No changes saved." in console.text


# Menu

def test_menu_choice_reprompts_until_valid(make_io):
    io, console = make_io(["9", "2"])

    assert io.get_menu_choice() == "2"
    assert "Invalid choice" in console.text


def test_menu_choice_exits_on_ctrl_d(make_io):
    io, _ = make_io([EOFError()])

    assert io.get_menu_choice() == "0"


def test_menu_lists_every_option(make_io):
    io, console = make_io()

    io.display_menu()

    for label in ("Create a new safety report", "Retry a failed assessment",
                  "Clarify and reassess a saved report", "Exit"):
        assert label in console.text


# Displays

@pytest.mark.parametrize("status, expected", [
    ("READY_FOR_REVIEW", "Status: Ready for review"),
    ("NEEDS_CLARIFICATION", "Status: Needs clarification"),
    ("INCOMPLETE", "Status: Incomplete"),
    ("UNKNOWN", "Assessment result unavailable."),
])
def test_display_assessment_result(make_io, status, expected):
    io, console = make_io()

    io.display_assessment_result({"status": status})

    assert expected in console.text


def test_display_clarification_questions(make_io):
    io, console = make_io()

    io.display_clarification_questions(["CLARIFY_LOCATION", "ADD_TIME", "NOT_A_CODE"])

    assert "more specific location" in console.text
    assert "Approximately what time" in console.text
    assert "Clarification question unavailable." in console.text


def test_quota_error_display(make_io):
    io, console = make_io()

    io.display_processing_error("QUOTA_EXHAUSTED")

    assert "AI usage limit reached" in console.text
    assert "The report was not assessed" in console.text


def test_save_error_display(make_io):
    io, console = make_io()

    io.display_processing_error("SAVE_FAILED")

    assert "The report could not be saved" in console.text
    assert "The report was not assessed" not in console.text


def test_unknown_error_display(make_io):
    io, console = make_io()

    io.display_processing_error("UNKNOWN")

    assert "An unexpected error occurred" in console.text
