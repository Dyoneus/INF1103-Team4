"""Tests for the Flask web interface. No live AI, database or report files are used."""

import io
from pathlib import Path

import pytest

from logic_manager import LogicManager
from web_app import (
    AccessControl, ReportPresenter, SafeReportWebApp, UploadedPhotos, WebNotifier, WebReportForm,
)

READY_FIELDS = {
    "issue_clarity": "CLEAR",
    "location_quality": "ADEQUATE",
    "date_quality": "EXACT",
    "time_quality": "EXACT",
    "safety_category": "ELECTRICAL",
}
VAGUE_LOCATION_FIELDS = {**READY_FIELDS, "location_quality": "VAGUE"}

VALID_FORM = {
    "description": "Sparks coming from an exposed cable near the loading bay.",
    "workplace_name": "Acme Warehouse",
    "workplace_location": "12 Hougang Ave 3, loading bay 2",
    "incident_datetime": "2024-01-05T09:30",
    "reporter_profile": "Employee of the workplace",
    "name": "Jane Tan",
    "email": "Jane@Example.com",
    "email_confirm": "jane@example.com",
    "nric_fin": "s1234567d",
    "contact_type": "Mobile",
    "contact_number": "9001 9001",
}

ADMIN_USERNAME = "safety-admin"
ADMIN_PASSWORD = "test-admin-password"

# Smallest useful stand-in for an uploaded photo: only the extension is checked.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class FakeAI:
    """Stands in for ai_manager: returns scripted fields instead of calling Groq."""

    def __init__(self, fields=None, configured=True, fails=False):
        self.fields = fields or READY_FIELDS
        self.configured = configured
        self.fails = fails
        self.calls = []
        self.photos_existed = []

    def ensure_ready(self):
        if not self.configured:
            raise RuntimeError("GROQ_API_KEY is not configured.")

    def analyze_incident(self, incident_report, photo_paths=None):
        self.calls.append((incident_report, list(photo_paths or [])))
        self.photos_existed.append([Path(path).is_file() for path in photo_paths or []])
        if self.fails:
            raise RuntimeError("Incident analysis failed.")
        return dict(self.fields)

    def make_result(self, reference_id, fields=None, error=None):
        result = {"reference_id": reference_id, "status": "error" if error else "success"}
        for field in READY_FIELDS:
            result[field] = fields[field] if fields and not error else None
        result["error"] = str(error) if error else None
        return result


class FakeData:
    """Stands in for data_manager: keeps reports in memory."""

    def __init__(self, reports=()):
        self.reports = {report["reference_id"]: report for report in reports}
        self.load_fails = False
        self.create_fails = False

    def load_reports(self):
        return None if self.load_fails else list(self.reports.values())

    def create_report(self, report):
        if self.create_fails:
            raise OSError("Could not save the report.")
        reference_id = f"TEST-{len(self.reports) + 1:03d}"
        self.reports[reference_id] = {
            "reference_id": reference_id,
            "submitted_at": "2024-01-05T10:00:00",
            **report,
        }
        return Path("reports") / f"{reference_id}.json"

    def save_report(self, reference_id, ai_result, assessment):
        self.reports[reference_id].update(ai_result=ai_result, assessment=assessment)
        return True

    def save_clarifications(self, reference_id, changes):
        self.reports[reference_id]["case_details"].update(changes)
        return True


def make_report(reference_id, status=None, codes=(), **case_details):
    report = {
        "reference_id": reference_id,
        "submitted_at": "2024-01-05T10:00:00",
        "case_details": {
            "description": "Wet floor with no warning sign.",
            "photos": [],
            "consent_for_image_use": None,
            "workplace_name": "Acme Warehouse",
            "workplace_location": "Hougang",
            "incident_datetime": "2024-01-05T09:30",
            "reporter_profile": "Employee of the workplace",
            **case_details,
        },
        "reporter": {
            "name": "Jane Tan", "email": "jane@example.com", "nric_fin": "S1234567D",
            "contact_type": "Mobile", "contact_number": "90019001",
        },
    }
    if status is not None:
        report["assessment"] = {"status": status, "clarification_codes": list(codes)}
    return report


@pytest.fixture
def make_client(tmp_path):
    """Return a factory: make_client(ai, data) -> Flask test client.

    The client is signed in as an admin unless admin=False (a member of the public).
    """
    def factory(ai=None, data=None, csrf=False, admin=True,
                admin_username=ADMIN_USERNAME, admin_password=ADMIN_PASSWORD):
        web = SafeReportWebApp(
            ai or FakeAI(), LogicManager(), data or FakeData(),
            reports_dir=tmp_path / "reports", secret_key="test",
            admin_username=admin_username, admin_password=admin_password,
        )
        web.flask_app.config.update(TESTING=True, CSRF_ENABLED=csrf, LOGIN_FAILURE_DELAY=0)
        client = web.flask_app.test_client()
        if admin:
            with client.session_transaction() as session:
                session["is_admin"] = True
        return client
    return factory


def test_health_endpoint_returns_ok(make_client):
    response = make_client().get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


# Dashboard

def test_dashboard_lists_reports_with_status_and_location_ranking(make_client):
    data = FakeData([
        make_report(
            "R-1", "READY_FOR_REVIEW",
            workplace_location="  Hougang   Avenue  1  ",
        ),
        make_report(
            "R-2", "AI_FAILED",
            workplace_location="hougang avenue 1",
        ),
        make_report("R-3", workplace_location="Jurong"),
        make_report("R-4", "READY_FOR_REVIEW", workplace_location="Ang Mo Kio"),
    ])

    response = make_client(data=data).get("/admin")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert all(reference in page for reference in ("R-1", "R-2", "R-3", "R-4"))
    assert "Ready for review" in page
    assert "Assessment failed" in page
    assert "Not assessed" in page

    ranking = page.split('<ol class="ranking">', 1)[1].split("</ol>", 1)[0]
    hougang = "<span>Hougang Avenue 1</span><b>2</b>"
    ang_mo_kio = "<span>Ang Mo Kio</span><b>1</b>"
    jurong = "<span>Jurong</span><b>1</b>"

    # Case and spacing differences must produce one location group.
    assert ranking.count("<li>") == 3
    # Highest report count first; alphabetical order breaks a tie.
    assert ranking.index(hougang) < ranking.index(ang_mo_kio) < ranking.index(jurong)


def test_dashboard_filters_by_status(make_client):
    data = FakeData([
        make_report("R-1", "READY_FOR_REVIEW"),
        make_report("R-2", "AI_FAILED"),
        make_report("R-3", "AI_FAILED", workplace_location="Jurong"),
    ])

    response = make_client(data=data).get("/admin?status=AI_FAILED")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "R-2" in page and "R-3" in page
    assert "R-1" not in page

    # The status filter changes the table; the summaries cover all reports.
    assert ">All <b>3</b>" in page
    assert ">Ready for review <b>1</b>" in page
    assert ">Assessment failed <b>2</b>" in page
    assert "<span>Hougang</span><b>2</b>" in page
    assert "<span>Jurong</span><b>1</b>" in page


def test_dashboard_reports_a_load_failure_without_crashing(make_client):
    data = FakeData()
    data.load_fails = True

    response = make_client(data=data).get("/admin")

    assert response.status_code == 200
    assert "Saved reports could not be loaded." in response.get_data(as_text=True)


# Creating a report

def test_valid_report_is_saved_assessed_and_shown(make_client):
    ai, data = FakeAI(), FakeData()
    client = make_client(ai, data)

    response = client.post("/", data=VALID_FORM, follow_redirects=True)
    page = response.get_data(as_text=True)

    saved = data.reports["TEST-001"]
    assert saved["case_details"]["incident_datetime"] == "2024-01-05T09:30"
    assert saved["case_details"]["consent_for_image_use"] is None
    assert saved["reporter"] == {
        "name": "Jane Tan", "email": "jane@example.com", "nric_fin": "S1234567D",
        "contact_type": "Mobile", "contact_number": "90019001",
    }
    assert saved["assessment"]["status"] == "READY_FOR_REVIEW"
    assert len(ai.calls) == 1 and "photos" not in ai.calls[0][0]
    assert "Reference ID: TEST-001" in page and "Assessment complete: Ready for review." in page


def test_report_page_masks_the_nric(make_client):
    page = make_client(data=FakeData([make_report("R-1")])).get("/reports/R-1").get_data(as_text=True)

    assert "*****567D" in page and "S1234567D" not in page


@pytest.mark.parametrize("field, value, message", [
    ("description", "   ", "Description cannot be empty."),
    ("incident_datetime", "2999-01-01T00:00", "The incident cannot be in the future."),
    ("email_confirm", "other@example.com", "The two email addresses do not match."),
    ("nric_fin", "S1234567A", "That NRIC/FIN is not valid."),
    ("contact_number", "61234567", "doesn&#39;t match the contact type"),
    ("reporter_profile", "Hacker", "Choose your relationship to the workplace."),
])
def test_invalid_report_is_rejected_and_nothing_is_saved(make_client, field, value, message):
    ai, data = FakeAI(), FakeData()

    response = make_client(ai, data).post("/", data={**VALID_FORM, field: value})

    assert response.status_code == 400
    assert message in response.get_data(as_text=True)
    assert data.reports == {} and ai.calls == []


def test_photos_reach_the_ai_only_with_consent_and_are_cleaned_up(make_client):
    ai, data = FakeAI(), FakeData()
    form = {
        **VALID_FORM,
        "consent_for_image_use": "yes",
        "photos": [(io.BytesIO(PNG_BYTES), "site.png"), (io.BytesIO(PNG_BYTES), "../evil.JPG")],
    }

    make_client(ai, data).post("/", data=form, content_type="multipart/form-data")

    sent_photos = ai.calls[0][1]
    assert [Path(path).name for path in sent_photos] == ["upload_1.png", "upload_2.jpg"]
    assert ai.photos_existed == [[True, True]]
    assert not any(Path(path).exists() for path in sent_photos)
    assert data.reports["TEST-001"]["case_details"]["consent_for_image_use"] is True


def test_photos_without_consent_are_not_sent_to_the_ai(make_client):
    ai = FakeAI()
    form = {**VALID_FORM, "photos": [(io.BytesIO(PNG_BYTES), "site.png")]}

    make_client(ai).post("/", data=form, content_type="multipart/form-data")

    assert ai.calls[0][1] == []


@pytest.mark.parametrize("names, message", [
    (["a.png", "b.png", "c.png", "d.png"], "at most 3 photos"),
    (["notes.pdf"], "Only .jpg, .jpeg and .png photos are accepted."),
])
def test_bad_photo_uploads_are_rejected(make_client, names, message):
    data = FakeData()
    form = {**VALID_FORM, "photos": [(io.BytesIO(PNG_BYTES), name) for name in names]}

    response = make_client(data=data).post(
        "/", data=form, content_type="multipart/form-data")

    assert response.status_code == 400
    assert message in response.get_data(as_text=True)
    assert data.reports == {}


def test_save_failure_is_reported(make_client):
    data = FakeData()
    data.create_fails = True

    response = make_client(data=data).post("/", data=VALID_FORM)

    assert response.status_code == 500
    assert "The report could not be saved." in response.get_data(as_text=True)


# AI failures and retrying

@pytest.mark.parametrize("ai, message", [
    (FakeAI(configured=False), "The AI API key has not been configured."),
    (FakeAI(fails=True), "AI processing could not be completed."),
])
def test_ai_failure_keeps_the_report_and_offers_a_retry(make_client, ai, message):
    data = FakeData()

    page = make_client(ai, data).post(
        "/", data=VALID_FORM, follow_redirects=True).get_data(as_text=True)

    assert data.reports["TEST-001"]["assessment"]["status"] == "AI_FAILED"
    assert message in page and "Retry assessment" in page


def test_retry_reassesses_the_same_report(make_client):
    data = FakeData([make_report("R-1", "AI_FAILED")])

    page = make_client(FakeAI(), data).post(
        "/reports/R-1/retry", follow_redirects=True).get_data(as_text=True)

    assert list(data.reports) == ["R-1"]
    assert data.reports["R-1"]["assessment"]["status"] == "READY_FOR_REVIEW"
    assert "Retry assessment" not in page


def test_retry_is_refused_for_an_assessed_report(make_client):
    ai = FakeAI()
    data = FakeData([make_report("R-1", "READY_FOR_REVIEW")])

    page = make_client(ai, data).post(
        "/reports/R-1/retry", follow_redirects=True).get_data(as_text=True)

    assert ai.calls == []
    assert "This report has already been assessed." in page


# Clarifying

def test_clarification_form_asks_only_for_flagged_fields(make_client):
    data = FakeData([make_report("R-1", "NEEDS_CLARIFICATION", ["CLARIFY_LOCATION"])])

    page = make_client(data=data).get("/reports/R-1").get_data(as_text=True)

    assert "Can you provide a more specific location?" in page
    assert 'name="workplace_location"' in page
    assert 'name="description"' not in page and 'name="incident_datetime"' not in page


def test_clarification_is_saved_and_reassessed(make_client):
    ai = FakeAI()
    data = FakeData([make_report("R-1", "NEEDS_CLARIFICATION", ["CLARIFY_LOCATION"])])

    make_client(ai, data).post(
        "/reports/R-1/clarify",
        data={"workplace_location": " Blk 5 Hougang Ave 1, level 2 ", "description": "ignored"})

    report = data.reports["R-1"]
    assert report["case_details"]["workplace_location"] == "Blk 5 Hougang Ave 1, level 2"
    assert report["case_details"]["description"] == "Wet floor with no warning sign."
    assert ai.calls[0][0]["workplace_location"] == "Blk 5 Hougang Ave 1, level 2"
    assert report["assessment"]["status"] == "READY_FOR_REVIEW"


def test_report_can_still_need_clarification_after_reassessment(make_client):
    data = FakeData([make_report("R-1", "INCOMPLETE", ["ADD_LOCATION"])])

    page = make_client(FakeAI(VAGUE_LOCATION_FIELDS), data).post(
        "/reports/R-1/clarify", data={"workplace_location": "Hougang"},
        follow_redirects=True).get_data(as_text=True)

    assert data.reports["R-1"]["assessment"] == {
        "status": "NEEDS_CLARIFICATION", "clarification_codes": ["CLARIFY_LOCATION"]}
    assert "Save and reassess" in page


def test_invalid_clarification_changes_nothing(make_client):
    ai = FakeAI()
    data = FakeData([make_report("R-1", "NEEDS_CLARIFICATION", ["CLARIFY_LOCATION"])])

    response = make_client(ai, data).post("/reports/R-1/clarify", data={"workplace_location": ""})

    assert response.status_code == 400
    assert "Workplace location cannot be empty." in response.get_data(as_text=True)
    assert data.reports["R-1"]["case_details"]["workplace_location"] == "Hougang"
    assert ai.calls == []


def test_clarify_is_refused_when_not_needed(make_client):
    ai = FakeAI()
    data = FakeData([make_report("R-1", "READY_FOR_REVIEW")])

    make_client(ai, data).post("/reports/R-1/clarify", data={"workplace_location": "Elsewhere"})

    assert data.reports["R-1"]["case_details"]["workplace_location"] == "Hougang"
    assert ai.calls == []


# Lookups, photos and security

def test_unknown_report_is_a_404(make_client):
    client = make_client()

    assert client.get("/reports/NOPE").status_code == 404
    assert client.post("/reports/NOPE/retry").status_code == 404


def test_photo_is_served_only_from_the_reports_own_folder(make_client, tmp_path):
    photo_folder = tmp_path / "reports" / "photos" / "R-1"
    photo_folder.mkdir(parents=True)
    photo = photo_folder / "photo_1.png"
    photo.write_bytes(PNG_BYTES)
    secret = tmp_path / "secret.png"
    secret.write_bytes(PNG_BYTES)
    data = FakeData([make_report("R-1", photos=[str(photo), str(secret)])])
    client = make_client(data=data)

    assert client.get("/reports/R-1/photos/1").data == PNG_BYTES
    assert client.get("/reports/R-1/photos/2").status_code == 404
    assert client.get("/reports/R-1/photos/3").status_code == 404


def test_post_without_csrf_token_is_rejected(make_client):
    data = FakeData()

    response = make_client(data=data, csrf=True).post("/", data=VALID_FORM)

    assert response.status_code == 400
    assert data.reports == {}


def test_post_with_the_page_csrf_token_is_accepted(make_client):
    data = FakeData()
    client = make_client(data=data, csrf=True)
    client.get("/")
    with client.session_transaction() as session:
        token = session["csrf_token"]

    client.post("/", data={**VALID_FORM, "csrf_token": token})

    assert "TEST-001" in data.reports


# Public and admin access

def test_home_page_is_the_public_report_form(make_client):
    response = make_client(admin=False).get("/")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Report a workplace safety concern" in page and 'name="description"' in page
    assert "Admin sign in" in page and "All reports" not in page


def test_dashboard_sends_the_public_to_the_sign_in_page(make_client):
    data = FakeData([make_report("R-1", "READY_FOR_REVIEW")])

    response = make_client(data=data, admin=False).get("/admin", follow_redirects=True)
    page = response.get_data(as_text=True)

    assert response.request.path == "/admin/login"
    assert "R-1" not in page


def test_admin_signs_in_with_username_and_password_and_sees_the_dashboard(make_client):
    data = FakeData([make_report("R-1", "READY_FOR_REVIEW")])
    client = make_client(data=data, admin=False)

    response = client.post(
        "/admin/login", data={"username": f" {ADMIN_USERNAME} ", "password": ADMIN_PASSWORD},
        follow_redirects=True)

    assert response.request.path == "/admin"
    assert "R-1" in response.get_data(as_text=True)


@pytest.mark.parametrize("username, password", [
    (ADMIN_USERNAME, "wrong"),
    (ADMIN_USERNAME, ADMIN_PASSWORD + "x"),
    (ADMIN_USERNAME, ""),
    ("someone-else", ADMIN_PASSWORD),
    (ADMIN_USERNAME.upper(), ADMIN_PASSWORD),
    ("", ADMIN_PASSWORD),
    ("", ""),
])
def test_wrong_username_or_password_is_refused_with_the_same_message(make_client, username, password):
    client = make_client(admin=False)

    response = client.post("/admin/login", data={"username": username, "password": password})
    page = response.get_data(as_text=True)

    assert response.status_code == 401
    assert "That username or password is not correct." in page
    assert password not in page or not password
    assert client.get("/admin").status_code == 302


@pytest.mark.parametrize("username, password", [
    (None, None), ("", ""), (ADMIN_USERNAME, None), (ADMIN_USERNAME, ""),
    (None, ADMIN_PASSWORD), ("   ", ADMIN_PASSWORD),
])
def test_nobody_can_sign_in_unless_both_username_and_password_are_set(make_client, username, password):
    client = make_client(admin=False, admin_username=username, admin_password=password)

    page = client.get("/admin/login").get_data(as_text=True)
    response = client.post(
        "/admin/login", data={"username": username or "", "password": password or ""})

    assert "SAFEREPORT_ADMIN_USERNAME" in page and "SAFEREPORT_ADMIN_PASSWORD" in page
    assert 'name="password"' not in page
    assert response.status_code == 401
    assert client.get("/admin").status_code == 302


def test_sign_out_ends_admin_access(make_client):
    client = make_client()

    client.post("/admin/logout")

    assert client.get("/admin").status_code == 302


def test_public_submitter_can_follow_up_their_own_report_only(make_client):
    ai = FakeAI(VAGUE_LOCATION_FIELDS)
    data = FakeData([make_report("R-1", "NEEDS_CLARIFICATION", ["CLARIFY_LOCATION"])])
    client = make_client(ai, data, admin=False)

    response = client.post("/", data=VALID_FORM, follow_redirects=True)
    own_page = response.get_data(as_text=True)
    reference_id = response.request.path.rsplit("/", 1)[-1]
    ai.fields = READY_FIELDS
    client.post(f"/reports/{reference_id}/clarify", data={"workplace_location": "Blk 5, level 2"})

    assert "Save and reassess" in own_page and "All reports" not in own_page
    assert data.reports[reference_id]["assessment"]["status"] == "READY_FOR_REVIEW"
    # Someone else's report stays out of reach.
    other = client.get("/reports/R-1", follow_redirects=True)
    assert other.request.path == "/admin/login"
    assert "Wet floor" not in other.get_data(as_text=True)


def test_public_cannot_change_or_view_other_reports(make_client, tmp_path):
    photo_folder = tmp_path / "reports" / "photos" / "R-1"
    photo_folder.mkdir(parents=True)
    photo = photo_folder / "photo_1.png"
    photo.write_bytes(PNG_BYTES)
    ai = FakeAI()
    data = FakeData([make_report("R-1", "AI_FAILED", photos=[str(photo)])])
    client = make_client(ai, data, admin=False)

    client.post("/reports/R-1/retry")
    client.post("/reports/R-1/clarify", data={"workplace_location": "Elsewhere"})

    assert ai.calls == []
    assert data.reports["R-1"]["assessment"]["status"] == "AI_FAILED"
    assert data.reports["R-1"]["case_details"]["workplace_location"] == "Hougang"
    assert client.get("/reports/R-1/photos/1").status_code == 404


def test_unknown_and_existing_reports_look_the_same_to_the_public(make_client):
    client = make_client(data=FakeData([make_report("R-1")]), admin=False)

    existing, unknown = client.get("/reports/R-1"), client.get("/reports/NOPE")

    assert existing.status_code == unknown.status_code == 302
    assert existing.location == unknown.location


# Classes on their own

def test_access_control_remembers_only_recent_reports(make_client):
    access = AccessControl(ADMIN_USERNAME, ADMIN_PASSWORD)
    app = make_client(admin=False).application

    with app.test_request_context():
        for number in range(25):
            access.remember_report(f"R-{number}")

        assert not access.can_view("R-0") and access.can_view("R-24")
        assert not access.is_admin()
        assert not access.sign_in(ADMIN_USERNAME, "nope")
        assert access.sign_in(ADMIN_USERNAME, ADMIN_PASSWORD)
        assert access.is_admin() and access.can_view("R-0")


def test_notifier_records_console_messages_for_the_web():
    notifier = WebNotifier()

    notifier.display_assessment_result({"status": "NEEDS_CLARIFICATION"})
    notifier.display_processing_error("TIMEOUT")
    notifier.display_processing_error("SAVE_FAILED")

    assert notifier.messages == [
        ("success", "Assessment complete: Needs clarification."),
        ("error", "The AI service took too long to respond. The report is saved but was not assessed."),
        ("error", "The report could not be saved."),
    ]


def test_presenter_handles_reports_with_missing_parts():
    presenter = ReportPresenter({"reference_id": "R-1", "assessment": "corrupt"})

    assert presenter.status == "NOT_ASSESSED" and presenter.can_retry
    assert presenter.clarification_codes == [] and not presenter.can_clarify
    assert presenter.photo_count == 0 and presenter.ai_result is None


def test_form_uses_the_injected_clock_for_future_dates():
    from datetime import datetime
    form = WebReportForm(clock=lambda: datetime(2020, 1, 1))

    report, errors = form.parse_report(VALID_FORM, [])

    assert report is None
    assert errors == {"incident_datetime": "The incident cannot be in the future."}


def test_form_maps_clarification_codes_to_fields():
    fields = WebReportForm().clarification_fields(["ADD_TIME", "CLARIFY_OBSERVATION", "ADD_DATE"])

    assert [field["name"] for field in fields] == ["description", "incident_datetime"]


def test_uploads_are_removed_even_if_the_request_fails():
    class Upload:
        filename = "site.png"

        def save(self, path):
            Path(path).write_bytes(PNG_BYTES)

    with pytest.raises(RuntimeError):
        with UploadedPhotos([Upload()]) as uploads:
            paths, errors = uploads.save()
            assert errors == [] and Path(paths[0]).is_file()
            raise RuntimeError("boom")

    assert not Path(paths[0]).exists()

def test_create_app_supplies_manager_instances(monkeypatch):
    from unittest.mock import Mock
    import ai_manager
    import data_manager
    import logic_manager
    import web_app

    ai = Mock(spec=ai_manager.AIManager)
    logic = Mock(spec=logic_manager.LogicManager)
    data = Mock(spec=data_manager.DataManager)

    ai_class = Mock(return_value=ai)
    logic_class = Mock(return_value=logic)
    data_class = Mock(return_value=data)
    web_class = Mock()

    monkeypatch.setattr(ai_manager, "AIManager", ai_class)
    monkeypatch.setattr(logic_manager, "LogicManager", logic_class)
    monkeypatch.setattr(data_manager, "DataManager", data_class)
    monkeypatch.setattr(web_app, "SafeReportWebApp", web_class)

    flask_app = web_app.create_app()

    ai_class.assert_called_once_with()
    logic_class.assert_called_once_with()
    data_class.assert_called_once_with()
    web_class.assert_called_once()

    arguments = web_class.call_args.kwargs
    assert arguments["ai_manager"] is ai
    assert arguments["logic_manager"] is logic
    assert arguments["data_manager"] is data
    assert flask_app is web_class.return_value.flask_app

@pytest.mark.parametrize(
    "method, path, status, expected_code",
    [
        ("GET", "/admin", "READY_FOR_REVIEW", 302),
        ("GET", "/reports/OTHER-001", "READY_FOR_REVIEW", 302),
        ("POST", "/reports/OTHER-001/retry", "AI_FAILED", 302),
        ("POST", "/reports/OTHER-001/clarify", "NEEDS_CLARIFICATION", 302),
        ("GET", "/reports/OTHER-001/photos/1", "READY_FOR_REVIEW", 404),
    ],
)
def test_denied_requests_do_not_reach_managers(
    make_client, method, path, status, expected_code
):
    from unittest.mock import Mock

    ai = FakeAI()
    codes = ["CLARIFY_LOCATION"] if status == "NEEDS_CLARIFICATION" else []
    data = FakeData([
        make_report("OWN-001", "READY_FOR_REVIEW"),
        make_report("OTHER-001", status, codes=codes),
    ])
    client = make_client(ai=ai, data=data, admin=False)

    with client.session_transaction() as session:
        session["my_reports"] = ["OWN-001"]

    data.load_reports = Mock(wraps=data.load_reports)
    data.save_report = Mock(wraps=data.save_report)
    data.save_clarifications = Mock(wraps=data.save_clarifications)
    ai.ensure_ready = Mock(wraps=ai.ensure_ready)

    if method == "POST":
        response = client.post(path, data={"workplace_location": "Block B"})
    else:
        response = client.get(path)

    assert response.status_code == expected_code
    if expected_code == 302:
        assert response.headers["Location"].endswith("/admin/login")

    data.load_reports.assert_not_called()
    data.save_report.assert_not_called()
    data.save_clarifications.assert_not_called()
    ai.ensure_ready.assert_not_called()
    assert ai.calls == []

def test_login_logout_and_load_failure_recovery(make_client):
    data = FakeData([make_report("SESSION-001", "READY_FOR_REVIEW")])
    client = make_client(data=data, admin=False, csrf=True)

    client.get("/admin/login")
    with client.session_transaction() as session:
        token = session["csrf_token"]

    rejected = client.post("/admin/login", data={
        "username": ADMIN_USERNAME,
        "password": "wrong-password",
        "csrf_token": token,
    })
    assert rejected.status_code == 401
    assert client.get("/admin").status_code == 302

    with client.session_transaction() as session:
        token = session["csrf_token"]

    signed_in = client.post("/admin/login", data={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD,
        "csrf_token": token,
    }, follow_redirects=True)
    assert signed_in.status_code == 200
    assert signed_in.request.path == "/admin"
    assert "SESSION-001" in signed_in.get_data(as_text=True)

    data.load_fails = True
    unavailable = client.get("/admin")
    assert unavailable.status_code == 200
    assert "Saved reports could not be loaded." in unavailable.get_data(as_text=True)
    assert "SESSION-001" not in unavailable.get_data(as_text=True)

    data.load_fails = False
    recovered = client.get("/admin")
    assert recovered.status_code == 200
    assert "SESSION-001" in recovered.get_data(as_text=True)
    assert "Saved reports could not be loaded." not in recovered.get_data(as_text=True)

    with client.session_transaction() as session:
        assert session.get("is_admin") is True
        token = session["csrf_token"]

    signed_out = client.post(
        "/admin/logout",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    assert signed_out.status_code == 200
    assert signed_out.request.path == "/"
    assert client.get("/admin").status_code == 302
    assert client.get("/reports/SESSION-001").status_code == 302