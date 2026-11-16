"""Flask web interface for SafeReport (the GUI advanced deliverable).

Run it from the repository root with:  python web_app.py

Classes
    AccessControl     Decides who may see what: admins see every report, the
                      public only the reports they submitted themselves.
    WebNotifier       Collects the messages the console would print, so the
                      same assessment workflow can run behind a web page.
    ReportPresenter   Turns a stored report into values a template can show.
    UploadedPhotos    Holds browser photo uploads in a temporary folder.
    WebReportForm     Validates browser form data with the Validator classes.
    SafeReportWebApp  Owns the Flask app and its routes, and hands the work to
                      the AI, Logic and Data managers it is given.

Relationships
    SafeReportWebApp composes  its Flask app, WebReportForm and AccessControl
                     (creates and owns them).
    SafeReportWebApp aggregates the AI, Logic and Data managers it is given
                     (they are shared with the console app and outlive it).
    WebReportForm    composes  its Validator objects, and uses every one of them
                     through the Validator interface (polymorphism).
    WebNotifier      is substituted for the console IOManager when
                     SafeReportApplication assesses a report (LSP): the workflow
                     only needs the display_* methods, not a terminal.
"""

import hmac
import os
import secrets
import shutil
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, abort, flash, redirect, render_template, request, send_file,
    session, url_for,
)

from io_manager import (
    ALLOWED_PHOTO_TYPES, ASSESSMENT_STATUS_LABELS, CLARIFICATION_QUESTIONS,
    CONTACT_TYPES, ERROR_MESSAGES, MAX_DESCRIPTION_LENGTH, MAX_LOCATION_LENGTH,
    MAX_NAME_LENGTH, MAX_PHOTOS, NOT_ASSESSED_ERRORS, PROCESSING_ERROR_MESSAGES,
    REPORTER_PROFILES,
)
from main import SafeReportApplication
from validators import (
    ContactNumberValidator, EmailValidator, IncidentDateTimeValidator,
    NricValidator, PhotoPathValidator, RequiredTextValidator, Validator,
)

# The format a browser <input type="datetime-local"> submits.
WEB_DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
MAX_UPLOAD_BYTES = 16 * 1024 * 1024

NOT_ASSESSED = "NOT_ASSESSED"
AI_FAILED = "AI_FAILED"
CLARIFIABLE_STATUSES = ("INCOMPLETE", "NEEDS_CLARIFICATION")
RETRYABLE_STATUSES = (AI_FAILED, NOT_ASSESSED)

STATUS_LABELS = {
    **ASSESSMENT_STATUS_LABELS,
    AI_FAILED: "Assessment failed",
    NOT_ASSESSED: "Not assessed",
}

WEB_ERROR_MESSAGES = {
    **ERROR_MESSAGES,
    "EMPTY_DATETIME": "Choose the date and time of the incident.",
    "INVALID_DATETIME": "Choose a valid date and time.",
    "EMAIL_MISMATCH": "The two email addresses do not match.",
    "INVALID_PROFILE": "Choose your relationship to the workplace.",
    "INVALID_CONTACT_TYPE": "Choose a contact number type.",
    "TOO_MANY_PHOTOS": f"You can attach at most {MAX_PHOTOS} photos.",
    "PHOTO_NOT_FOUND": "A photo could not be uploaded. Please try again.",
}


class AccessControl:
    """Who may see what.

    The report form is public. An admin, signed in with the admin username and
    password, may see every report. Anyone else may only see the reports they submitted from
    this browser, which are remembered in their signed session cookie.
    """

    _MAX_REMEMBERED_REPORTS = 20

    def __init__(self, admin_username: str | None, admin_password: str | None):
        self._admin_username = (admin_username or "").strip()
        self._admin_password = admin_password or ""

    @property
    def admin_enabled(self) -> bool:
        """False unless both a username and a password are configured: nobody can sign in."""
        return bool(self._admin_username and self._admin_password)

    def is_admin(self) -> bool:
        return self.admin_enabled and session.get("is_admin") is True

    def sign_in(self, username: str, password: str) -> bool:
        if not self.admin_enabled:
            return False
        # compare_digest takes the same time whether or not the guess is close.
        # Both are always checked, so a wrong username is no quicker than a wrong password.
        username_ok = hmac.compare_digest(
            username.strip().encode(), self._admin_username.encode())
        password_ok = hmac.compare_digest(password.encode(), self._admin_password.encode())
        if not (username_ok and password_ok):
            return False
        session.clear()  # Start a fresh session for the admin.
        session["is_admin"] = True
        return True

    def sign_out(self) -> None:
        session.pop("is_admin", None)

    def remember_report(self, reference_id: str) -> None:
        """Let this browser come back to a report it has just submitted."""
        remembered = [*session.get("my_reports", []), reference_id]
        session["my_reports"] = remembered[-self._MAX_REMEMBERED_REPORTS:]

    def can_view(self, reference_id: str) -> bool:
        return self.is_admin() or reference_id in session.get("my_reports", [])


class WebNotifier:
    """Records what the console IOManager would print.

    SafeReportApplication.assess_report() reports its outcome through
    display_assessment_result() and display_processing_error(). This class
    offers the same two methods, so that workflow runs unchanged for the web.
    """

    def __init__(self):
        self._messages: list[tuple[str, str]] = []

    @property
    def messages(self) -> list[tuple[str, str]]:
        """(category, text) pairs, in the order they were reported."""
        return list(self._messages)

    def display_assessment_result(self, assessment: dict) -> None:
        label = ASSESSMENT_STATUS_LABELS.get(assessment.get("status"))
        if label is None:
            self._messages.append(("error", "Assessment result unavailable."))
        else:
            self._messages.append(("success", f"Assessment complete: {label}."))

    def display_processing_error(self, error_code: str) -> None:
        text = PROCESSING_ERROR_MESSAGES.get(error_code, "An unexpected error occurred.")
        if error_code in NOT_ASSESSED_ERRORS:
            text += " The report is saved but was not assessed."
        self._messages.append(("error", text))


class ReportPresenter:
    """Read-only view of one stored report for the templates."""

    def __init__(self, report: dict):
        self._report = report

    @property
    def reference_id(self) -> str:
        return str(self._report.get("reference_id", ""))

    @property
    def submitted_at(self) -> str:
        return str(self._report.get("submitted_at", "")).replace("T", " ")

    @property
    def case_details(self) -> dict:
        details = self._report.get("case_details")
        return details if isinstance(details, dict) else {}

    @property
    def reporter(self) -> dict:
        reporter = self._report.get("reporter")
        return reporter if isinstance(reporter, dict) else {}

    @property
    def incident_datetime(self) -> str:
        return str(self.case_details.get("incident_datetime", "")).replace("T", " ")

    @property
    def photo_count(self) -> int:
        photos = self.case_details.get("photos")
        return len(photos) if isinstance(photos, list) else 0

    @property
    def masked_nric(self) -> str:
        """Show only the last four characters, e.g. *****567D."""
        nric = str(self.reporter.get("nric_fin", ""))
        return "*" * max(len(nric) - 4, 0) + nric[-4:]

    @property
    def ai_result(self) -> dict | None:
        result = self._report.get("ai_result")
        if isinstance(result, dict) and result.get("status") == "success":
            return result
        return None

    @property
    def status(self) -> str:
        assessment = self._report.get("assessment")
        if isinstance(assessment, dict) and assessment.get("status") in STATUS_LABELS:
            return assessment["status"]
        return NOT_ASSESSED

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def clarification_codes(self) -> list[str]:
        assessment = self._report.get("assessment")
        if not isinstance(assessment, dict):
            return []
        codes = assessment.get("clarification_codes")
        return list(codes) if isinstance(codes, list) else []

    @property
    def clarification_questions(self) -> list[str]:
        return [
            CLARIFICATION_QUESTIONS.get(code, "Clarification question unavailable.")
            for code in self.clarification_codes
        ]

    @property
    def can_retry(self) -> bool:
        return self.status in RETRYABLE_STATUSES

    @property
    def can_clarify(self) -> bool:
        return self.status in CLARIFIABLE_STATUSES and bool(self.clarification_codes)


class UploadedPhotos:
    """Browser photo uploads, kept in a temporary folder until the report is saved.

    The Data Manager copies photos into reports/photos/<reference_id>/, so the
    temporary copies are only needed while the request is handled. Use as a
    context manager so they are always removed.
    """

    def __init__(self, files, max_photos: int = MAX_PHOTOS):
        self._files = [file for file in files if file and file.filename]
        self._max_photos = max_photos
        self._folder: str | None = None

    def __enter__(self) -> "UploadedPhotos":
        return self

    def __exit__(self, *exc_info) -> None:
        self.discard()

    def save(self) -> tuple[list[str], list[str]]:
        """Write the uploads to disk. Return (paths, error codes)."""
        if len(self._files) > self._max_photos:
            return [], ["TOO_MANY_PHOTOS"]
        if not self._files:
            return [], []

        self._folder = tempfile.mkdtemp(prefix="safereport-upload-")
        paths = []
        for number, file in enumerate(self._files, start=1):
            # Never trust the browser's file name: keep only its extension.
            suffix = Path(file.filename).suffix.lower()
            path = Path(self._folder) / f"upload_{number}{suffix}"
            file.save(path)
            paths.append(str(path))
        return paths, []

    def discard(self) -> None:
        if self._folder is not None:
            shutil.rmtree(self._folder, ignore_errors=True)
            self._folder = None


class WebReportForm:
    """Validates a report submitted from the browser.

    Mirrors io_manager.ReportForm: the same Validator classes and limits decide
    what is acceptable, so the console and the web accept exactly the same data.
    """

    # Which case field each clarification code asks the user to correct.
    _CLARIFICATION_FIELDS = (
        (("CLARIFY_OBSERVATION",), "description", "Description"),
        (("ADD_LOCATION", "CLARIFY_LOCATION"), "workplace_location", "Workplace location"),
        (("ADD_DATE", "ADD_TIME"), "incident_datetime", "Date and time of incident"),
    )

    def __init__(self, clock=datetime.now):
        self._case_validators: dict[str, Validator] = {
            "description": RequiredTextValidator(
                MAX_DESCRIPTION_LENGTH, "EMPTY_DESCRIPTION", "DESCRIPTION_TOO_LONG"),
            "workplace_name": RequiredTextValidator(
                MAX_NAME_LENGTH, "EMPTY_WORKPLACE_NAME", "NAME_TOO_LONG"),
            "workplace_location": RequiredTextValidator(
                MAX_LOCATION_LENGTH, "EMPTY_LOCATION", "LOCATION_TOO_LONG"),
            "incident_datetime": IncidentDateTimeValidator(WEB_DATETIME_FORMAT, clock),
        }
        self._reporter_validators: dict[str, Validator] = {
            "name": RequiredTextValidator(MAX_NAME_LENGTH, "EMPTY_NAME", "NAME_TOO_LONG"),
            "email": EmailValidator(),
            "nric_fin": NricValidator(),
        }
        self._photo_validator = PhotoPathValidator(ALLOWED_PHOTO_TYPES)

    def parse_report(self, form, photo_paths: list[str]) -> tuple[dict | None, dict[str, str]]:
        """Return (report, {}) when valid, otherwise (None, {field: message})."""
        errors: dict[str, str] = {}

        case_details = self._validate_fields(form, self._case_validators, errors)
        reporter = self._validate_fields(form, self._reporter_validators, errors)

        photos = []
        for path in photo_paths:
            codes = self._photo_validator.validate(path)
            if codes:
                errors["photos"] = self._message(codes[0])
                break
            photos.append(self._photo_validator.clean(path))

        profile = form.get("reporter_profile", "")
        if profile not in REPORTER_PROFILES.values():
            errors["reporter_profile"] = self._message("INVALID_PROFILE")

        if "email" not in errors:
            confirm = EmailValidator().clean(form.get("email_confirm", ""))
            if confirm != reporter["email"]:
                errors["email_confirm"] = self._message("EMAIL_MISMATCH")

        contact_type = form.get("contact_type", "")
        if contact_type not in CONTACT_TYPES.values():
            errors["contact_type"] = self._message("INVALID_CONTACT_TYPE")
        else:
            # The valid first digit depends on the type, so this one is made per request.
            reporter.update(self._validate_fields(
                form, {"contact_number": ContactNumberValidator(contact_type)}, errors))

        if errors:
            return None, errors

        case_details["photos"] = photos
        # Consent only applies when photos are attached (as in the console form).
        case_details["consent_for_image_use"] = (
            form.get("consent_for_image_use") == "yes" if photos else None)
        case_details["reporter_profile"] = profile
        reporter["contact_type"] = contact_type
        return {"case_details": case_details, "reporter": reporter}, {}

    def clarification_fields(self, codes: list[str]) -> list[dict]:
        """The fields the assessment flagged, in display order."""
        return [
            {"name": field, "label": label}
            for step_codes, field, label in self._CLARIFICATION_FIELDS
            if any(code in codes for code in step_codes)
        ]

    def parse_clarifications(self, form, codes: list[str]) -> tuple[dict | None, dict[str, str]]:
        """Validate only the flagged fields. Return (changes, {}) or (None, errors)."""
        wanted = {
            field["name"]: self._case_validators[field["name"]]
            for field in self.clarification_fields(codes)
        }
        errors: dict[str, str] = {}
        changes = self._validate_fields(form, wanted, errors)
        return (None, errors) if errors else (changes, {})

    def _validate_fields(self, form, validators: dict[str, Validator], errors: dict[str, str]) -> dict:
        """Run each field through its validator; works with any Validator subclass."""
        cleaned = {}
        for field, validator in validators.items():
            value = form.get(field, "")
            codes = validator.validate(value)
            if codes:
                errors[field] = self._message(codes[0])
            else:
                cleaned[field] = validator.clean(value)
        return cleaned

    @staticmethod
    def _message(code: str) -> str:
        return WEB_ERROR_MESSAGES.get(code, "Invalid input.")


class SafeReportWebApp:
    """The web GUI: a public report form, and an admin-only list of every report."""

    def __init__(
        self,
        ai_manager,
        logic_manager,
        data_manager,
        reports_dir: Path | str = "reports",
        secret_key: str | None = None,
        admin_username: str | None = None,
        admin_password: str | None = None,
    ):
        self._ai = ai_manager
        self._logic = logic_manager
        self._data = data_manager
        self._reports_dir = Path(reports_dir)
        self._form = WebReportForm()
        self._access = AccessControl(admin_username, admin_password)

        self._flask = Flask(__name__)
        self._flask.config.update(
            SECRET_KEY=secret_key or secrets.token_hex(32),
            MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            CSRF_ENABLED=True,
            # Seconds to wait after a failed admin sign-in, to slow down guessing.
            LOGIN_FAILURE_DELAY=1.0,
        )
        self._register_routes()

    @property
    def flask_app(self) -> Flask:
        return self._flask

    def run(self, host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
        # threaded=True keeps other pages responsive while one request waits for the AI.
        self._flask.run(host=host, port=port, debug=debug, threaded=True)

    # Setup

    def _register_routes(self) -> None:
        add = self._flask.add_url_rule
        # Public: the report form is the home page.
        add("/", "new_report", self._new_report, methods=["GET", "POST"])
        # Admins only.
        add("/admin", "dashboard", self._dashboard)
        add("/admin/login", "admin_login", self._admin_login, methods=["GET", "POST"])
        add("/admin/logout", "admin_logout", self._admin_logout, methods=["POST"])
        # Admins, and the person who submitted that report from this browser.
        add("/reports/<reference_id>", "report_detail", self._report_detail)
        add("/reports/<reference_id>/retry", "retry_report", self._retry_report, methods=["POST"])
        add("/reports/<reference_id>/clarify", "clarify_report", self._clarify_report, methods=["POST"])
        add("/reports/<reference_id>/photos/<int:number>", "report_photo", self._report_photo)

        self._flask.before_request(self._check_csrf_token)
        self._flask.context_processor(lambda: {
            "csrf_token": self._csrf_token,
            "is_admin": self._access.is_admin(),
        })
        self._flask.register_error_handler(413, self._upload_too_large)

    # Cross-site request forgery protection

    def _csrf_token(self) -> str:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)
        return session["csrf_token"]

    def _check_csrf_token(self) -> None:
        if request.method != "POST" or not self._flask.config["CSRF_ENABLED"]:
            return
        expected = session.get("csrf_token", "")
        submitted = request.form.get("csrf_token", "")
        if not expected or not hmac.compare_digest(expected, submitted):
            abort(400, "This form has expired. Go back, reload the page and try again.")

    def _upload_too_large(self, _error):
        flash("Those photos are too large to upload (16 MB in total).", "error")
        return redirect(url_for("new_report"))

    # Pages

    def _admin_login(self):
        if self._access.is_admin():
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "")
            if self._access.sign_in(username, request.form.get("password", "")):
                return redirect(url_for("dashboard"))
            time.sleep(self._flask.config["LOGIN_FAILURE_DELAY"])
            # Never say which of the two was wrong.
            flash("That username or password is not correct.", "error")

        status = 200 if request.method == "GET" else 401
        return render_template(
            "admin_login.html",
            admin_enabled=self._access.admin_enabled,
            username=request.form.get("username", ""),
        ), status

    def _admin_logout(self):
        self._access.sign_out()
        flash("You have signed out.", "success")
        return redirect(url_for("new_report"))

    def _dashboard(self):
        if not self._access.is_admin():
            return redirect(url_for("admin_login"))

        reports = self._data.load_reports()
        if reports is None:
            flash(PROCESSING_ERROR_MESSAGES["LOAD_FAILED"], "error")
            reports = []

        presenters = sorted(
            (ReportPresenter(report) for report in reports),
            key=lambda presenter: presenter.submitted_at,
            reverse=True,
        )
        counts = Counter(presenter.status for presenter in presenters)

        selected = request.args.get("status", "")
        if selected in STATUS_LABELS:
            presenters = [p for p in presenters if p.status == selected]
        else:
            selected = ""

        return render_template(
            "dashboard.html",
            reports=presenters,
            total=sum(counts.values()),
            counts=counts,
            status_labels=STATUS_LABELS,
            selected_status=selected,
            locations=self._logic.sort_reports_by_location(reports),
        )

    def _new_report(self):
        if request.method == "GET":
            return self._render_report_form({}, {})

        with UploadedPhotos(request.files.getlist("photos")) as uploads:
            photo_paths, upload_errors = uploads.save()
            report, errors = self._form.parse_report(request.form, photo_paths)

            if upload_errors:
                errors["photos"] = WEB_ERROR_MESSAGES[upload_errors[0]]
            if errors:
                if photo_paths and "photos" not in errors:
                    errors["photos"] = "Please choose your photos again."
                return self._render_report_form(request.form, errors), 400

            try:
                report_path = self._data.create_report(report)
            except OSError:
                flash(PROCESSING_ERROR_MESSAGES["SAVE_FAILED"], "error")
                return self._render_report_form(request.form, {}), 500

            reference_id = Path(report_path).stem
            self._access.remember_report(reference_id)
            flash(f"Report saved. Reference ID: {reference_id}", "success")
            # Assess before leaving the block: the AI reads the uploaded photos.
            self._assess(reference_id, report)

        return redirect(url_for("report_detail", reference_id=reference_id))

    def _report_detail(self, reference_id: str):
        if not self._access.can_view(reference_id):
            return self._refuse_access()
        report = self._find_report(reference_id)
        return self._render_report_detail(report, {}, {})

    def _retry_report(self, reference_id: str):
        if not self._access.can_view(reference_id):
            return self._refuse_access()
        report = self._find_report(reference_id)

        if ReportPresenter(report).can_retry:
            self._assess(reference_id, report)
        else:
            flash("This report has already been assessed.", "error")

        return redirect(url_for("report_detail", reference_id=reference_id))

    def _clarify_report(self, reference_id: str):
        if not self._access.can_view(reference_id):
            return self._refuse_access()
        report = self._find_report(reference_id)
        presenter = ReportPresenter(report)

        if not presenter.can_clarify:
            flash("This report does not need clarification.", "error")
            return redirect(url_for("report_detail", reference_id=reference_id))

        changes, errors = self._form.parse_clarifications(
            request.form, presenter.clarification_codes)
        if errors:
            return self._render_report_detail(report, request.form, errors), 400

        if not self._data.save_clarifications(reference_id, changes):
            flash(PROCESSING_ERROR_MESSAGES["SAVE_FAILED"], "error")
            return redirect(url_for("report_detail", reference_id=reference_id))

        report["case_details"].update(changes)
        self._assess(reference_id, report)
        return redirect(url_for("report_detail", reference_id=reference_id))

    def _report_photo(self, reference_id: str, number: int):
        if not self._access.can_view(reference_id):
            abort(404)
        photos = ReportPresenter(self._find_report(reference_id)).case_details.get("photos")
        if not isinstance(photos, list) or not 1 <= number <= len(photos):
            abort(404)

        # Only ever serve files stored inside this report's own photo folder.
        allowed_folder = (self._reports_dir / "photos" / reference_id).resolve()
        path = Path(str(photos[number - 1])).resolve()
        if allowed_folder not in path.parents or not path.is_file():
            abort(404)

        return send_file(path)

    # Helpers

    def _refuse_access(self):
        """Same answer whether or not the report exists, so IDs cannot be probed."""
        flash("Sign in as an admin to view that report.", "error")
        return redirect(url_for("admin_login"))

    def _find_report(self, reference_id: str) -> dict:
        reports = self._data.load_reports()
        if reports is None:
            abort(500, PROCESSING_ERROR_MESSAGES["LOAD_FAILED"])

        for report in reports:
            if report.get("reference_id") == reference_id:
                return report
        abort(404)

    def _assess(self, reference_id: str, report: dict) -> None:
        """Run the shared AI -> Logic -> Data workflow and flash what happened."""
        notifier = WebNotifier()
        workflow = SafeReportApplication(notifier, self._ai, self._logic, self._data)
        workflow.assess_report(reference_id, report)

        for category, text in notifier.messages:
            flash(text, category)

    def _render_report_form(self, values, errors: dict[str, str]):
        return render_template(
            "report_form.html",
            values=values,
            errors=errors,
            profiles=list(REPORTER_PROFILES.values()),
            contact_types=list(CONTACT_TYPES.values()),
            max_description=MAX_DESCRIPTION_LENGTH,
            max_name=MAX_NAME_LENGTH,
            max_location=MAX_LOCATION_LENGTH,
            max_photos=MAX_PHOTOS,
            photo_types=",".join(sorted(ALLOWED_PHOTO_TYPES)),
            now=datetime.now().strftime(WEB_DATETIME_FORMAT),
        )

    def _render_report_detail(self, report: dict, values, errors: dict[str, str]):
        presenter = ReportPresenter(report)
        return render_template(
            "report_detail.html",
            report=presenter,
            clarification_fields=self._form.clarification_fields(presenter.clarification_codes),
            values=values,
            errors=errors,
            max_description=MAX_DESCRIPTION_LENGTH,
            max_location=MAX_LOCATION_LENGTH,
            now=datetime.now().strftime(WEB_DATETIME_FORMAT),
        )


def create_app() -> Flask:
    """Build the web app on the real managers (also used by `flask --app web_app run`)."""
    import ai_manager
    import data_manager
    import logic_manager

    web_app = SafeReportWebApp(
        ai_manager=ai_manager.AIManager(),
        logic_manager=logic_manager.LogicManager(),
        data_manager=data_manager,
        secret_key=os.environ.get("SAFEREPORT_SECRET_KEY"),
        admin_username=os.environ.get("SAFEREPORT_ADMIN_USERNAME"),
        admin_password=os.environ.get("SAFEREPORT_ADMIN_PASSWORD"),
    )
    return web_app.flask_app


if __name__ == "__main__":
    create_app().run(
        host=os.environ.get("SAFEREPORT_HOST", "127.0.0.1"),
        port=int(os.environ.get("SAFEREPORT_PORT", "5000")),
        threaded=True,
    )
