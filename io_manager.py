"""Terminal input and output for SafeReport (the I/O Manager).

Classes
    ConsolePrompter  Generic terminal prompts that re-ask until input is valid.
                     Knows nothing about safety reports.
    ReportView       Everything the user sees: menu, summaries, results, errors.
    ReportForm       Collects, reviews and clarifies one safety report.
    IOManager        The single object the rest of the application talks to.

Relationships
    IOManager  composes  ConsolePrompter, ReportView and ReportForm (creates and owns them).
    ReportForm composes  its Validator objects (creates and owns them).
    ReportForm aggregates the ConsolePrompter and ReportView it is given
               (they are shared with IOManager and exist independently of the form).
    ConsolePrompter is associated with the Validator interface: ask_until_valid()
               works with any Validator subclass without type checks (polymorphism).
"""

from typing import Callable, NamedTuple

from validators import (
    Validator, RequiredTextValidator, EmailValidator, NricValidator,
    ContactNumberValidator, IncidentDateTimeValidator, PhotoPathValidator,
)

InputFn = Callable[[str], str]
OutputFn = Callable[..., None]

MAX_DESCRIPTION_LENGTH = 2000  # The maximum length of a safety report description.
MAX_NAME_LENGTH = 100
MAX_LOCATION_LENGTH = 200
MAX_PHOTOS = 3
ALLOWED_PHOTO_TYPES = {".jpg", ".jpeg", ".png"}
DATETIME_FORMAT = "%Y-%m-%d %H:%M"
DATETIME_HINT = "YYYY-MM-DD HH:MM"
DIVIDER = "-" * 48

# Ctrl+C and Ctrl+D while typing.
CANCEL_KEYS = (EOFError, KeyboardInterrupt)

MENU_OPTIONS = {
    "1": "Create a new safety report",
    "2": "Retry a failed assessment",
    "3": "Clarify and reassess a saved report",
    "0": "Exit",
}

REPORTER_PROFILES = {
    "1": "Employee of the workplace",
    "2": "Contractor / subcontractor worker",
    "3": "Visitor / member of the public",
    "4": "Other",
}

CONTACT_TYPES = {"1": "Home", "2": "Mobile", "3": "Office"}

REVIEW_CASE_DETAILS = "Case details"
REVIEW_CONTACT_DETAILS = "Contact details"
REVIEW_SUBMIT = "Submit report"
REVIEW_SECTIONS = {"1": REVIEW_CASE_DETAILS, "2": REVIEW_CONTACT_DETAILS, "0": REVIEW_SUBMIT}

# Messages for the error codes returned by validators.py.
ERROR_MESSAGES = {
    "EMPTY_DESCRIPTION": "Description cannot be empty. Please try again.",
    "DESCRIPTION_TOO_LONG": f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters.",
    "EMPTY_LOCATION": "Workplace location cannot be empty.",
    "LOCATION_TOO_LONG": f"Location exceeds {MAX_LOCATION_LENGTH} characters.",
    "NAME_TOO_LONG": f"Name exceeds {MAX_NAME_LENGTH} characters.",
    "EMPTY_NAME": "Name cannot be empty.",
    "EMPTY_WORKPLACE_NAME": "Workplace name cannot be empty.",
    "PHOTO_NOT_FOUND": "File not found. Check the path and try again.",
    "PHOTO_BAD_TYPE": "Only .jpg, .jpeg and .png photos are accepted.",
    "EMPTY_DATETIME": f"Date and time cannot be empty. Use {DATETIME_HINT}.",
    "INVALID_DATETIME": "Invalid format. Use YYYY-MM-DD HH:MM, e.g. 2026-10-09 14:30.",
    "FUTURE_DATETIME": "The incident cannot be in the future.",
    "EMPTY_EMAIL": "Email cannot be empty.",
    "INVALID_EMAIL": "That doesn't look like a valid email address.",
    "EMPTY_NRIC": "NRIC/FIN cannot be empty.",
    "INVALID_NRIC_FORMAT": "Enter a valid NRIC/FIN, e.g. S1234567D.",
    "INVALID_NRIC_CHECKSUM": "That NRIC/FIN is not valid. Please check the last letter.",
    "EMPTY_CONTACT_NUMBER": "Contact number cannot be empty.",
    "INVALID_CONTACT_NUMBER": "Enter an 8-digit Singapore number (optionally with +65).",
    "WRONG_NUMBER_TYPE": "That number doesn't match the contact type you chose.",
}

# Questions for the clarification codes returned by the Logic Manager.
CLARIFICATION_QUESTIONS = {
    "CLARIFY_OBSERVATION": "Please describe what you observed in more detail.",
    "ADD_LOCATION": "Where did you observe this?",
    "CLARIFY_LOCATION": "Can you provide a more specific location?",
    "ADD_DATE": "What date did this happen?",
    "ADD_TIME": "Approximately what time did this happen?",
}

ASSESSMENT_STATUS_LABELS = {
    "READY_FOR_REVIEW": "Ready for review",
    "NEEDS_CLARIFICATION": "Needs clarification",
    "INCOMPLETE": "Incomplete",
}

# Messages for the processing error codes used by main.py.
PROCESSING_ERROR_MESSAGES = {
    "QUOTA_EXHAUSTED": "AI usage limit reached. Please try again later.",
    "RATE_LIMITED": "Too many AI requests. Please try again later.",
    "TIMEOUT": "The AI service took too long to respond.",
    "INVALID_JSON": "The AI returned an invalid response.",
    "INVALID_SCHEMA": "The AI response is missing required information.",
    "CONFIG_MISSING": "The AI API key has not been configured.",
    "AI_FAILED": "AI processing could not be completed. Please try again later.",
    "SAVE_FAILED": "The report could not be saved.",
    "LOAD_FAILED": "Saved reports could not be loaded.",
}

# Errors after which the report is saved but has no assessment yet.
NOT_ASSESSED_ERRORS = frozenset({
    "QUOTA_EXHAUSTED", "RATE_LIMITED", "TIMEOUT",
    "INVALID_JSON", "INVALID_SCHEMA", "CONFIG_MISSING",
})


def _default_input(prompt: str) -> str:
    # Looked up at call time so tests that monkeypatch builtins.input still work.
    return input(prompt)


def _default_output(text: str = "") -> None:
    print(text)


class ConsolePrompter:
    """Reads terminal input and re-prompts until it is valid.

    Ctrl+C / Ctrl+D are not caught here: they propagate as KeyboardInterrupt /
    EOFError so the caller decides what "cancel" means at that point.
    """

    def __init__(
        self,
        error_messages: dict[str, str],
        input_fn: InputFn | None = None,
        output_fn: OutputFn | None = None,
    ):
        self._error_messages = error_messages
        self._input = input_fn or _default_input
        self._output = output_fn or _default_output

    def show(self, text: str = "") -> None:
        self._output(text)

    def show_errors(self, codes: list[str]) -> None:
        for code in codes:
            self.show(self._error_messages.get(code, "Invalid input."))

    def ask(self, prompt: str) -> str:
        return self._input(prompt).strip()

    def ask_until_valid(self, prompt: str, validator: Validator, optional: bool = False) -> str | None:
        """Keep asking until the validator returns no error codes.

        Works with any Validator subclass. If optional is True, a blank answer returns None.
        """
        while True:
            value = self.ask(prompt)

            if optional and not value:
                return None

            errors = validator.validate(value)
            if not errors:
                return validator.clean(value)

            self.show_errors(errors)

    def ask_choice(self, prompt: str, options: dict[str, str]) -> str:
        """Show a numbered menu and return the chosen option's label."""
        self.show(prompt)
        for key, label in options.items():
            self.show(f"  {key}. {label}")

        while True:
            choice = self.ask("Select an option: ")
            if choice in options:
                return options[choice]
            self.show(f"Invalid choice. Please enter one of: {', '.join(options)}.")

    def ask_yes_no(self, prompt: str) -> bool:
        """Ask a yes/no question and return True for yes."""
        while True:
            answer = self.ask(f"{prompt} (y/n): ").lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            self.show("Please answer y or n.")


class ReportView:
    """Displays menus, reports, assessment results and errors. Never reads input."""

    def __init__(self, output_fn: OutputFn | None = None):
        self._output = output_fn or _default_output

    def _show(self, text: str = "") -> None:
        self._output(text)

    def display_menu(self) -> None:
        self._show("\nSafeReport!")
        self._show(DIVIDER)
        for key, label in MENU_OPTIONS.items():
            self._show(f"{key}. {label}")
        self._show(DIVIDER)

    def display_report_summary(self, report: dict) -> None:
        """Display the full completed report so the user can review it."""
        case_details = report.get("case_details", {})
        reporter = report.get("reporter", {})

        self._show("\nReport summary")
        self._show(DIVIDER)
        self._show("Case details:")
        self._show(f"  Description: {case_details.get('description', '')}")
        self._show(f"  Photos: {len(case_details.get('photos', []))} attached")
        self._show(f"  Consent for photo use: {'Yes' if case_details.get('consent_for_image_use') else 'No'}")
        self._show(f"  Workplace name: {case_details.get('workplace_name', '')}")
        self._show(f"  Workplace location: {case_details.get('workplace_location', '')}")
        self._show(f"  Incident date/time: {case_details.get('incident_datetime', '')}")
        self._show(f"  Reporter profile: {case_details.get('reporter_profile', '')}")
        self._show("\nContact details:")
        self._show(f"  Name: {reporter.get('name', '')}")
        self._show(f"  Email: {reporter.get('email', '')}")
        self._show(f"  NRIC/FIN: {reporter.get('nric_fin', '')}")
        self._show(f"  Contact type: {reporter.get('contact_type', '')}")
        self._show(f"  Contact number: {reporter.get('contact_number', '')}")
        self._show(DIVIDER)

    def display_report_reference(self, reference_id: str) -> None:
        self._show(f"\nReport saved locally. Reference ID: {reference_id}")

    def display_saved_reports(self, reports: list[dict]) -> None:
        self._show("\nSaved reports:")
        for number, report in enumerate(reports, start=1):
            self._show(f"{number}. {report['reference_id']}")

    def display_assessment_result(self, assessment: dict) -> None:
        self._show("\nReport Assessment")
        self._show(DIVIDER)

        label = ASSESSMENT_STATUS_LABELS.get(assessment.get("status"))
        if label is None:
            self._show("Assessment result unavailable.")
        else:
            self._show(f"Status: {label}")

    def display_clarification_questions(self, codes: list[str]) -> None:
        if not codes:
            return

        self._show("\nPlease clarify the following:")
        for code in codes:
            question = CLARIFICATION_QUESTIONS.get(code, "Clarification question unavailable.")
            self._show(f"- {question}")

    def display_processing_error(self, error_code: str) -> None:
        self._show("\nSafeReport Error")
        self._show(DIVIDER)
        self._show(PROCESSING_ERROR_MESSAGES.get(error_code, "An unexpected error occurred."))

        if error_code in NOT_ASSESSED_ERRORS:
            self._show("The report was not assessed.")

    def display_report_analysis_started(self, filename: str, photo_count: int) -> None:
        self._show(f"Analyzing {filename} with {photo_count} photo(s)...")

    def display_analysis_summary(self, output_path: str, total: int, successful: int, failed: int) -> None:
        self._show(f"\nAI results saved to: {output_path}")
        self._show(f"Total reports: {total}")
        self._show(f"Successful: {successful}")
        self._show(f"Failed: {failed}")

    def display_analysis_error(self, message: str) -> None:
        self._show(f"Error: {message}")


class _ClarificationStep(NamedTuple):
    """One field the user may be asked to correct, and the codes that trigger it."""
    codes: tuple[str, ...]
    field: str
    label: str
    ask: Callable[[], str]


class ReportForm:
    """Collects a safety report from the user, lets them review it and answer clarifications.

    The private _ask_* / _collect_* methods let Ctrl+C propagate. The public
    methods are the only places that decide what cancelling means.
    """

    def __init__(self, prompter: ConsolePrompter, view: ReportView):
        self._prompter = prompter
        self._view = view

        self._description_validator = RequiredTextValidator(
            MAX_DESCRIPTION_LENGTH, "EMPTY_DESCRIPTION", "DESCRIPTION_TOO_LONG")
        self._location_validator = RequiredTextValidator(
            MAX_LOCATION_LENGTH, "EMPTY_LOCATION", "LOCATION_TOO_LONG")
        self._workplace_name_validator = RequiredTextValidator(
            MAX_NAME_LENGTH, "EMPTY_WORKPLACE_NAME", "NAME_TOO_LONG")
        self._person_name_validator = RequiredTextValidator(
            MAX_NAME_LENGTH, "EMPTY_NAME", "NAME_TOO_LONG")
        self._email_validator = EmailValidator()
        self._nric_validator = NricValidator()
        self._datetime_validator = IncidentDateTimeValidator(DATETIME_FORMAT)
        self._photo_validator = PhotoPathValidator(ALLOWED_PHOTO_TYPES)

        # To support a new clarification code, add a row here.
        self._clarification_steps = (
            _ClarificationStep(("CLARIFY_OBSERVATION",), "description", "description",
                               self._ask_description),
            _ClarificationStep(("ADD_LOCATION", "CLARIFY_LOCATION"), "workplace_location", "location",
                               self._ask_updated_location),
            _ClarificationStep(("ADD_DATE", "ADD_TIME"), "incident_datetime", "date/time",
                               self._ask_incident_datetime),
        )

    # Public operations

    def collect_report(self) -> dict | None:
        """Collect the full report, or return None if the user cancels."""
        try:
            case_details = self._collect_case_details()
            reporter = self._collect_contact_details()
        except CANCEL_KEYS:
            self._prompter.show("\nReport entry cancelled.")
            return None

        return {"case_details": case_details, "reporter": reporter}

    def review_before_submission(self, report: dict | None) -> dict | None:
        """Let the user review the whole report and update any section before saving."""
        if not isinstance(report, dict):
            return report

        self._view.display_report_summary(report)

        try:
            wants_changes = self._prompter.ask_yes_no(
                "Would you like to make any changes before submitting this report?")

            while wants_changes:
                section = self._prompter.ask_choice(
                    "\nWhich section would you like to edit?", REVIEW_SECTIONS)
                if section == REVIEW_SUBMIT:
                    break

                self._edit_section(report, section)
                self._view.display_report_summary(report)
                wants_changes = self._prompter.ask_yes_no("Would you like to make any further changes?")

        except CANCEL_KEYS + (OSError,):
            pass  # Cancelling a review question submits the report as it is.

        return report

    def collect_clarifications(self, report: dict) -> dict | None:
        """Ask only for the fields the assessment flagged.

        Returns the changes without modifying the report, or None if the user cancels.
        """
        codes = report.get("assessment", {}).get("clarification_codes", [])
        self._view.display_clarification_questions(codes)
        details = report.get("case_details", {})
        changes = {}

        try:
            for step in self._clarification_steps:
                if any(code in codes for code in step.codes):
                    self._prompter.show(f"\nCurrent {step.label}: {details.get(step.field, '')}")
                    changes[step.field] = step.ask()
        except CANCEL_KEYS:
            self._prompter.show("\nClarification cancelled. No changes saved.")
            return None

        return changes

    # Sections

    def _edit_section(self, report: dict, section: str) -> None:
        """Replace one section. If the user cancels part-way, the old section is kept."""
        try:
            if section == REVIEW_CASE_DETAILS:
                report["case_details"] = self._collect_case_details()
            elif section == REVIEW_CONTACT_DETAILS:
                report["reporter"] = self._collect_contact_details()
        except CANCEL_KEYS:
            self._prompter.show("\nEdit cancelled. Your previous details were kept.")

    def _collect_case_details(self) -> dict:
        description = self._ask_description()
        photos = self._ask_photos()

        consent = None
        if photos:
            self._prompter.show("\nYour photos may be used by the authorities when handling this report.")
            consent = self._prompter.ask_yes_no("Do you consent to the use of these images?")

        self._prompter.show()
        workplace_name = self._prompter.ask_until_valid("Workplace name: ", self._workplace_name_validator)
        location = self._prompter.ask_until_valid("Workplace location: ", self._location_validator)
        incident_datetime = self._ask_incident_datetime()
        profile = self._prompter.ask_choice(
            "\nYour profile (your relationship to the workplace):", REPORTER_PROFILES)

        return {
            "description": description,
            "photos": photos,
            "consent_for_image_use": consent,
            "workplace_name": workplace_name,
            "workplace_location": location,
            "incident_datetime": incident_datetime,
            "reporter_profile": profile,
        }

    def _collect_contact_details(self) -> dict:
        self._prompter.show("\nEnter your contact details:")
        name = self._prompter.ask_until_valid("Name: ", self._person_name_validator)
        email = self._ask_verified_email()
        nric = self._prompter.ask_until_valid("NRIC/FIN: ", self._nric_validator)
        contact_type, contact_number = self._ask_contact_number()

        return {
            "name": name,
            "email": email,
            "nric_fin": nric,
            "contact_type": contact_type,
            "contact_number": contact_number,
        }

    # Individual fields

    def _ask_description(self) -> str:
        self._prompter.show("\nDescribe the workplace safety and health lapse, then press Enter to submit.")
        self._prompter.show(f"Maximum length: {MAX_DESCRIPTION_LENGTH} characters.")
        self._prompter.show("Press Ctrl+C to cancel.")
        return self._prompter.ask_until_valid("> ", self._description_validator)

    def _ask_photos(self) -> list[str]:
        """Collect up to MAX_PHOTOS photo file paths (optional)."""
        self._prompter.show(f"\nAdd photos (optional, up to {MAX_PHOTOS}; .jpg, .jpeg or .png).")
        self._prompter.show("Enter a file path, or press Enter to skip / finish.")

        photos: list[str] = []
        while len(photos) < MAX_PHOTOS:
            path = self._prompter.ask_until_valid(
                f"Photo {len(photos) + 1} path: ", self._photo_validator, optional=True)
            if path is None:
                break
            if path in photos:
                self._prompter.show("You already added that photo.")
                continue
            photos.append(path)

        return photos

    def _ask_verified_email(self) -> str:
        """Ask for an email twice and return it once both entries match."""
        while True:
            email = self._prompter.ask_until_valid("Email: ", self._email_validator)
            confirm = self._email_validator.clean(self._prompter.ask("Re-enter email to verify: "))

            if email == confirm:
                return email
            self._prompter.show("Emails do not match. Please try again.")

    def _ask_contact_number(self) -> tuple[str, str]:
        """Return (contact_type, normalised_number)."""
        contact_type = self._prompter.ask_choice("\nContact number type:", CONTACT_TYPES)
        # The valid first digit depends on the type chosen, so this validator is made per answer.
        number = self._prompter.ask_until_valid(
            f"{contact_type} number: ", ContactNumberValidator(contact_type))
        return contact_type, number

    def _ask_updated_location(self) -> str:
        return self._prompter.ask_until_valid("Updated workplace location: ", self._location_validator)

    def _ask_incident_datetime(self) -> str:
        return self._prompter.ask_until_valid(
            f"Date and time of incident ({DATETIME_HINT}): ", self._datetime_validator)


class IOManager:
    """The I/O Manager: the only object other managers need for terminal input and output."""

    def __init__(self, input_fn: InputFn | None = None, output_fn: OutputFn | None = None):
        self._prompter = ConsolePrompter(ERROR_MESSAGES, input_fn, output_fn)
        self._view = ReportView(output_fn)
        self._form = ReportForm(self._prompter, self._view)

    # Menus and selection

    def display_menu(self) -> None:
        self._view.display_menu()

    def get_menu_choice(self) -> str:
        """Return a valid menu choice, or '0' if input is cancelled."""
        while True:
            try:
                choice = self._prompter.ask("Select an option: ")
            except CANCEL_KEYS:
                self._prompter.show("\nInput cancelled.")
                return "0"

            if choice in MENU_OPTIONS:
                return choice
            self._prompter.show("Invalid choice. Please enter 0, 1, 2 or 3.")

    def select_saved_report(self, reports: list[dict]) -> dict | None:
        """Select a report by number or reference ID; return None if cancelled."""
        if not reports:
            self._prompter.show("\nNo matching reports found.")
            return None

        self._view.display_saved_reports(reports)

        while True:
            try:
                choice = self._prompter.ask("Report number or reference ID (0 to cancel): ")
            except CANCEL_KEYS:
                self._prompter.show("\nSelection cancelled.")
                return None

            if choice == "0":
                return None
            for number, report in enumerate(reports, start=1):
                if choice in (str(number), report["reference_id"]):
                    return report
            self._prompter.show("Please select one of the listed reports.")

    # Report entry

    def collect_report(self) -> dict | None:
        return self._form.collect_report()

    def review_report_before_submission(self, report: dict | None) -> dict | None:
        return self._form.review_before_submission(report)

    def collect_clarifications(self, report: dict) -> dict | None:
        return self._form.collect_clarifications(report)

    # Output

    def display_report_reference(self, reference_id: str) -> None:
        self._view.display_report_reference(reference_id)

    def display_assessment_result(self, assessment: dict) -> None:
        self._view.display_assessment_result(assessment)

    def display_clarification_questions(self, codes: list[str]) -> None:
        self._view.display_clarification_questions(codes)

    def display_processing_error(self, error_code: str) -> None:
        self._view.display_processing_error(error_code)

    def display_report_analysis_started(self, filename: str, photo_count: int) -> None:
        self._view.display_report_analysis_started(filename, photo_count)

    def display_analysis_summary(self, output_path: str, total: int, successful: int, failed: int) -> None:
        self._view.display_analysis_summary(output_path, total, successful, failed)

    def display_analysis_error(self, message: str) -> None:
        self._view.display_analysis_error(message)


# Transitional module-level names.
# main.py and ai_manager.py still call io_manager.<name>(...), and their tests
# monkeypatch these names. Each one is just a bound method of one shared
# IOManager, so all behaviour lives in the classes above. Delete this block once
# main.py and ai_manager.py create and hold their own IOManager instance.
_default_io = IOManager()

display_menu = _default_io.display_menu
get_menu_choice = _default_io.get_menu_choice
select_saved_report = _default_io.select_saved_report
collect_report = _default_io.collect_report
review_report_before_submission = _default_io.review_report_before_submission
collect_clarifications = _default_io.collect_clarifications
display_report_reference = _default_io.display_report_reference
display_assessment_result = _default_io.display_assessment_result
display_clarification_questions = _default_io.display_clarification_questions
display_processing_error = _default_io.display_processing_error
display_report_analysis_started = _default_io.display_report_analysis_started
display_analysis_summary = _default_io.display_analysis_summary
display_analysis_error = _default_io.display_analysis_error
