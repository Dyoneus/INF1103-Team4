"""Terminal input and output for SafeReport"""

import re
from datetime import datetime
from pathlib import Path

from report_store import save_report

MAX_DESCRIPTION_LENGTH = 2000  # The maximum length of a safety report description.
MAX_NAME_LENGTH = 100
MAX_LOCATION_LENGTH = 200
MAX_PHOTOS = 3
ALLOWED_PHOTO_TYPES = {".jpg", ".jpeg", ".png"}
DATETIME_FORMAT = "%Y-%m-%d %H:%M"
DATETIME_HINT = "YYYY-MM-DD HH:MM"

REPORTER_PROFILES = {
    "1": "Employee of the workplace",
    "2": "Contractor / subcontractor worker",
    "3": "Visitor / member of the public",
    "4": "Other",
}

CONTACT_TYPES = {"1": "Home", "2": "Mobile", "3": "Office"}

ERROR_MESSAGES = {
    "EMPTY_DESCRIPTION": "Description cannot be empty. Please try again.",
    "DESCRIPTION_TOO_LONG": f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters.",
    "EMPTY_LOCATION": "Workplace location cannot be empty.",
    "LOCATION_TOO_LONG": f"Location exceeds {MAX_LOCATION_LENGTH} characters.",
    "NAME_TOO_LONG": f"Name exceeds {MAX_NAME_LENGTH} characters.",
    "EMPTY_NAME": "Name cannot be empty.",
    "EMPTY_WORKPLACE_NAME": "Contractor or workplace name cannot be empty.",
    "PHOTO_NOT_FOUND": "File not found. Check the path and try again.",
    "PHOTO_BAD_TYPE": "Only .jpg, .jpeg and .png photos are accepted.",
    "INVALID_DATETIME": "Invalid format. Use YYYY-MM-DD HH:MM, e.g. 2026-10-09 14:30.",
    "FUTURE_DATETIME": "The incident cannot be in the future.",
    "EMPTY_EMAIL": "Email cannot be empty.",
    "INVALID_EMAIL": "That doesn't look like a valid email address.",
    "INVALID_NRIC_FORMAT": "Enter a valid NRIC/FIN, e.g. S1234567D.",
    "INVALID_NRIC_CHECKSUM": "That NRIC/FIN is not valid. Please check the last letter.",
    "INVALID_CONTACT_NUMBER": "Enter an 8-digit Singapore number (optionally with +65).",
    "WRONG_NUMBER_TYPE": "That number doesn't match the contact type you chose.",
}


"""Menu func starts here"""
def display_menu() -> None:
    """Display the menu."""
    print("\nSafeReport!")
    print("-" * 48)
    print("1. Create a new safety report")
    print("0. Exit")
    print("-" * 48)


def get_menu_choice() -> str:
    """Return a valid menu choice, or '0' if input is cancelled"""

    while True:
        try:
            choice = input("Select an option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nInput cancelled.")
            return "0"

        if choice == "1" or choice == "0":
            return choice

        print("Invalid choice. Please enter 1 or 0.")


"""Prompt helpers"""
def ask(prompt: str) -> str:
    """Prompt for input.

    Ctrl+C / Ctrl+D raise KeyboardInterrupt / EOFError, which
    collect_report() catches to cancel the whole report.
    """
    return input(prompt).strip()


def ask_until_valid(prompt: str, validate, optional: bool = False) -> str | None:
    """Keep asking until validate(value) returns no error codes.

    If optional is True, a blank answer returns None.
    """
    while True:
        value = ask(prompt)

        if optional and not value:
            return None

        errors = validate(value)
        if not errors:
            return value

        for error in errors:
            print(ERROR_MESSAGES.get(error, "Invalid input."))


def ask_choice(prompt: str, options: dict[str, str]) -> str:
    """Show a numbered menu and return the chosen option's label."""
    print(prompt)
    for key, label in options.items():
        print(f"  {key}. {label}")

    while True:
        choice = ask("Select an option: ")
        if choice in options:
            return options[choice]
        print(f"Invalid choice. Please enter one of: {', '.join(options)}.")


def ask_yes_no(prompt: str) -> bool:
    """Ask a yes/no question and return True for yes."""
    while True:
        answer = ask(f"{prompt} (y/n): ").lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


"""Collect description starts here"""
def get_report_text() -> str | None:
    """Collect report description, or return None if cancelled"""
    print("\nDescribe the workplace safety and health lapse, then press Enter to submit.")
    print(f"Maximum length: {MAX_DESCRIPTION_LENGTH} characters.")
    print("Press Ctrl+C to cancel.")

    while True:
        try:
            description = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nReport entry cancelled.")
            return None

        errors = validate_report_text(description, MAX_DESCRIPTION_LENGTH)

        if not errors:
            return description

        for error in errors:
            print(ERROR_MESSAGES[error])


"""Validation checks"""
def validate_report_text(text: str, max_chars: int) -> list[str]:
    """If error, return error codes for blank & over-length descriptions."""
    text = text.strip()
    errors = []

    if not text:
        errors.append("EMPTY_DESCRIPTION")

    if len(text) > max_chars:
        errors.append("DESCRIPTION_TOO_LONG")

    return errors


def validate_location(text: str) -> list[str]:
    """Return error codes for a blank or over-length location."""
    text = text.strip()
    if not text:
        return ["EMPTY_LOCATION"]
    if len(text) > MAX_LOCATION_LENGTH:
        return ["LOCATION_TOO_LONG"]
    return []


def validate_workplace_name(text: str) -> list[str]:
    """Return error codes for a blank or over-length workplace/contractor name."""
    text = text.strip()
    if not text:
        return ["EMPTY_WORKPLACE_NAME"]
    if len(text) > MAX_NAME_LENGTH:
        return ["NAME_TOO_LONG"]
    return []


def validate_person_name(text: str) -> list[str]:
    """Return error codes for a blank or over-length personal name."""
    text = text.strip()
    if not text:
        return ["EMPTY_NAME"]
    if len(text) > MAX_NAME_LENGTH:
        return ["NAME_TOO_LONG"]
    return []


def clean_path(text: str) -> Path:
    """Turn typed or drag-and-dropped text into a Path (strips quotes, expands ~)."""
    return Path(text.strip().strip("\"'")).expanduser()


def validate_photo_path(text: str) -> list[str]:
    """Return error codes if the path isn't an existing .jpg/.jpeg/.png file."""
    path = clean_path(text)
    if not path.is_file():
        return ["PHOTO_NOT_FOUND"]
    if path.suffix.lower() not in ALLOWED_PHOTO_TYPES:
        return ["PHOTO_BAD_TYPE"]
    return []


def validate_incident_datetime(text: str) -> list[str]:
    """Return error codes for a badly formatted or future date/time."""
    try:
        incident = datetime.strptime(text.strip(), DATETIME_FORMAT)
    except ValueError:
        return ["INVALID_DATETIME"]
    if incident > datetime.now():
        return ["FUTURE_DATETIME"]
    return []


def validate_email(text: str) -> list[str]:
    """Return error codes for a blank or badly formatted email."""
    text = text.strip()
    if not text:
        return ["EMPTY_EMAIL"]
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}", text):
        return ["INVALID_EMAIL"]
    return []


def validate_nric(text: str) -> list[str]:
    """Return error codes for an invalid Singapore NRIC/FIN.

    S/T/F/G numbers are checked against the official checksum letter.
    M-series FINs are only checked for format.
    """
    value = text.strip().upper()
    if not re.fullmatch(r"[STFGM]\d{7}[A-Z]", value):
        return ["INVALID_NRIC_FORMAT"]

    prefix = value[0]
    if prefix == "M":
        return []

    weights = (2, 7, 6, 5, 4, 3, 2)
    total = sum(int(digit) * weight for digit, weight in zip(value[1:8], weights))
    if prefix in "TG":
        total += 4

    checksum_letters = "JZIHGFEDCBA" if prefix in "ST" else "XWUTRQPNMLK"
    if value[8] != checksum_letters[total % 11]:
        return ["INVALID_NRIC_CHECKSUM"]
    return []


def normalise_phone(text: str) -> str:
    """Strip spaces, dashes and a leading +65 / 65 from a phone number."""
    digits = re.sub(r"[\s\-()]", "", text)
    if digits.startswith("+65"):
        digits = digits[3:]
    elif digits.startswith("65") and len(digits) == 10:
        digits = digits[2:]
    return digits


def validate_contact_number(text: str, contact_type: str) -> list[str]:
    """Return error codes for a Singapore number that doesn't fit its type.

    Mobile numbers start with 8 or 9. Home and office lines start with 6.
    """
    number = normalise_phone(text)
    if not re.fullmatch(r"\d{8}", number):
        return ["INVALID_CONTACT_NUMBER"]

    allowed_first_digits = "89" if contact_type == "Mobile" else "6"
    if number[0] not in allowed_first_digits:
        return ["WRONG_NUMBER_TYPE"]
    return []


"""Collect each section of the report"""
def get_photos() -> list[str]:
    """Collect up to MAX_PHOTOS photo file paths (optional)."""
    print(f"\nAdd photos (optional, up to {MAX_PHOTOS}; .jpg, .jpeg or .png).")
    print("Enter a file path, or press Enter to skip / finish.")

    photos: list[str] = []
    while len(photos) < MAX_PHOTOS:
        text = ask(f"Photo {len(photos) + 1} path: ")
        if not text:
            break

        errors = validate_photo_path(text)
        if errors:
            for error in errors:
                print(ERROR_MESSAGES[error])
            continue

        resolved = str(clean_path(text).resolve())
        if resolved in photos:
            print("You already added that photo.")
            continue

        photos.append(resolved)

    return photos


def get_verified_email() -> str:
    """Ask for an email twice and return it once both entries match."""
    while True:
        email = ask_until_valid("Email: ", validate_email).lower()
        confirm = ask("Re-enter email to verify: ").lower()

        if email == confirm:
            return email
        print("Emails do not match. Please try again.")


def get_contact_number() -> tuple[str, str]:
    """Return (contact_type, normalised_number)."""
    contact_type = ask_choice("\nContact number type:", CONTACT_TYPES)
    number = ask_until_valid(
        f"{contact_type} number: ",
        lambda value: validate_contact_number(value, contact_type),
    )
    return contact_type, normalise_phone(number)


def collect_case_details() -> dict | None:
    """Collect the details of the case, or return None if cancelled."""
    description = get_report_text()
    if description is None:
        return None

    photos = get_photos()

    consent = None
    if photos:
        print("\nYour photos may be used by the authorities when handling this report.")
        consent = ask_yes_no("Do you consent to the use of these images?")

    print()
    workplace_name = ask_until_valid(
        "Contractor or workplace name: ",
        validate_workplace_name,
    )
    location = ask_until_valid("Workplace location: ", validate_location)
    incident_text = ask_until_valid(
        f"Date and time of incident ({DATETIME_HINT}): ",
        validate_incident_datetime,
    )
    profile = ask_choice("\nYour profile (your relationship to the workplace):", REPORTER_PROFILES)

    return {
        "description": description,
        "photos": photos,
        "consent_for_image_use": consent,
        "workplace_or_contractor_name": workplace_name,
        "workplace_location": location,
        "incident_datetime": datetime.strptime(incident_text, DATETIME_FORMAT).isoformat(timespec="minutes"),
        "reporter_profile": profile,
    }


def collect_contact_details() -> dict:
    """Collect the reporter's contact details."""
    print("\nEnter your contact details:")
    name = ask_until_valid("Name: ", validate_person_name)
    email = get_verified_email()
    nric = ask_until_valid("NRIC/FIN: ", validate_nric).upper()
    contact_type, contact_number = get_contact_number()

    return {
        "name": name,
        "email": email,
        "nric_fin": nric,
        "contact_type": contact_type,
        "contact_number": contact_number,
    }


def collect_report() -> dict | None:
    """Collect the full report, or return None if the user cancels."""
    try:
        case_details = collect_case_details()
        if case_details is None:
            return None
        reporter = collect_contact_details()
    except (EOFError, KeyboardInterrupt):
        print("\nReport entry cancelled.")
        return None

    return {"case_details": case_details, "reporter": reporter}


"""For running io_manager.py easily/debugging"""
def run() -> None:
    """Show the menu and handle report creation until the user exits."""
    while True:
        display_menu()
        choice = get_menu_choice()

        if choice == "0":
            print("Exiting SafeReport.")
            return

        report = collect_report()
        if report is None:
            continue

        try:
            report_path = save_report(report)
        except OSError as error:
            print(f"\nCould not save the report: {error}")
            continue

        print(f"\nReport submitted and saved to {report_path}")


if __name__ == "__main__":
    run()