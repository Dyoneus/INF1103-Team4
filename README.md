# SafeReport

SafeReport is a terminal application for recording workplace safety reports. It validates report details and stores each submitted report and any attached photos as JSON and image files.

## Requirements

- Python 3.12 or later for running locally
- Docker Desktop (or another Docker Engine) for running in a container
- Docker Compose v2.24 or later (for optional `.env` file support)
- A Groq API key for AI assessments (reports can still be saved without it)

## Run locally

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

On macOS or Linux, activate the virtual environment with:

```sh
source .venv/bin/activate
```

Submitted reports and copied photos are saved under `reports/`. That directory is local application data and is excluded from Git.

Both `python main.py` open the SafeReport menu:

- **1. Create a new safety report** saves the report and assesses its readiness.
- **2. Retry a failed assessment** lists failed reports. Select a number or reference ID to retry and update that same report.
- **3. Clarify and reassess a saved report** lists incomplete reports and reports needing clarification. Answer the requested questions to update and reassess the same record.
- **0. Exit** closes the application. In report selection, 0 cancels instead.

Clarification answers are saved together before reassessment. Ctrl+C during the questions cancels without saving changes. If AI then fails, the corrections remain saved and option 2 can retry them. Reference IDs, reporter details and attached photos are preserved.

## Configure the AI API

The interactive application calls AI after saving a new report, retrying a failed assessment, or saving clarification answers. A missing API key leaves the report saved with status `AI_FAILED`, ready to retry after configuration.

For Docker, copy `.env.example` to `.env` and enter the key for your chosen AI provider. Docker Compose passes the AI provider settings and `.env` variables into the containers, including the key named by `AI_API_KEY_ENV`. For an OpenAI-compatible provider, set `AI_PROVIDER=openai`, `AI_MODEL`, `AI_BASE_URL` when needed, and `AI_API_KEY_ENV` to the environment variable holding the key. Do not commit `.env`.

For local use, `.env` is not loaded automatically. Set the key in the current shell before running `python main.py`:

```powershell
$env:GROQ_API_KEY = "your_actual_groq_api_key"
```

On macOS or Linux:

```sh
export GROQ_API_KEY="your_actual_groq_api_key"
```

The interactive application stores AI results and readiness assessments in each report JSON file. The optional batch script, `python ai_manager.py`, writes separate results to `ai_output.json` by default; `AI_OUTPUT_PATH` changes that destination. Batch output does not update saved readiness assessments; use menu option 2 for retries.

## Run with Docker

### Start the report-entry app

Run these commands from the repository root (the folder containing `docker-compose.yml`):

```powershell
docker compose build
docker compose run --rm safereport
```

To enable AI assessment, configure `.env` as described above and run `docker compose run --rm safereport`. Compose passes the key to the app, which calls Groq when a report is submitted. Without a configured key, the app still saves reports but cannot assess them.

The app is interactive. Choose **1. Create a new safety report**, complete the prompts, and let it finish saving before exiting. A report JSON file is created only after a report has been completed and submitted.

### Where the files go

Compose connects folders on your computer to folders inside the container:

| On your computer | Inside the container | Contents |
|---|---|---|
| `reports/` | `/app/reports` | Submitted report JSON files and copied photos |
| `data/` | `/data` | SQLite database (`safereport.db`) and AI analysis results, including `ai_output.json` |

This is a **bind mount**: the container writes directly into these project folders. Files remain on your computer after the container exits, even though `--rm` removes the temporary container. The SQLite database path in Docker is `/data/safereport.db`, backed by `data/safereport.db` on your computer. Docker creates the host folders if they do not already exist.

If you do not see a new report, check that you ran the command from the repository root and completed report submission. Then refresh the `reports/` folder in your editor or File Explorer.

To run the AI analysis script in Docker, copy `.env.example` to `.env`, set a valid Groq API key, and run:

```sh
docker compose run --rm safereport python ai_manager.py
```

This AI step is separate from entering a report and requires a valid API key. It reads JSON report files from `reports/` and writes analysis results to `data/ai_output.json`. The report and result directories may contain personal or sensitive data. Keep them private and do not commit them.

Use the Compose commands above if you want files to appear in the project folders. If you run the image directly with `docker run` and mount a **named volume** at `/app/reports`, Docker keeps the files in its own managed storage; they will persist, but they will not appear in the project’s local `reports/` folder.

## Web interface (GUI)

`web_app.py` is a Flask web interface over the same four managers as the terminal menu. Reports created in one show up in the other.

Run it locally from the repository root, with the virtual environment active:

```powershell
python -m pip install -r requirements.txt
$env:GROQ_API_KEY = "your_actual_groq_api_key"
$env:SAFEREPORT_ADMIN_USERNAME = "choose_an_admin_username"
$env:SAFEREPORT_ADMIN_PASSWORD = "choose_an_admin_password"
python web_app.py
```

Then open <http://127.0.0.1:5000>. Stop the server with Ctrl+C.

Or run it in Docker (reads `GROQ_API_KEY`, `SAFEREPORT_ADMIN_USERNAME` and `SAFEREPORT_ADMIN_PASSWORD` from `.env`):

```sh
docker compose up --build web
```

### Who can see what

| Page | Who | What it does | Terminal equivalent |
|---|---|---|---|
| Report form (`/`) | Everyone | Validates the form, saves the report and photos, then assesses it | Menu option 1 |
| Report page (`/reports/<id>`) | Admins, and the person who submitted it | Shows the report and its assessment. **Retry assessment** reruns a failed assessment; **Save and reassess** asks only for the details the assessment flagged | Menu options 2 and 3 |
| Admin sign in (`/admin/login`) | Everyone | Signs the admin in with `SAFEREPORT_ADMIN_USERNAME` and `SAFEREPORT_ADMIN_PASSWORD` | - |
| All reports (`/admin`) | Admins | Lists saved reports, filters them by status, and ranks locations by report count | - |

A member of the public can reopen only the reports they submitted from the same browser (remembered in their session cookie), so they can answer clarification questions without seeing anyone else's report. If either `SAFEREPORT_ADMIN_USERNAME` or `SAFEREPORT_ADMIN_PASSWORD` is not set, nobody can sign in as an admin. The username is case-sensitive. Do not commit the password; keep it in `.env` or your shell.

### How it fits the design

- `SafeReportWebApp` owns the Flask app and routes. It is given the AI, Logic and Data managers, so tests pass in fakes.
- `AccessControl` decides who may see what: admin sign-in, sign-out, and which reports a visitor submitted.
- `WebReportForm` checks browser input with the same `Validator` subclasses as the terminal form.
- `WebNotifier` stands in for the terminal `IOManager`, so `SafeReportApplication.assess_report()` runs unchanged and its messages appear on the page.
- `tests/test_web_app.py` covers the pages and the access rules with Flask's test client, without a live AI call.

The web interface uses Flask's development server and listens on `127.0.0.1` only, which suits local use and demos. Hosting it for real public use would need a production WSGI server and HTTPS. Optional settings: `SAFEREPORT_HOST`, `SAFEREPORT_PORT`, and `SAFEREPORT_SECRET_KEY` (keeps sessions valid across restarts).

## Tests

SafeReport includes automated tests for the four managers and the main application workflow.

### Business Rule Test Script

`test_script.py` demonstrates the business rules implemented in `logic_manager.py` using predefined AI outputs.

The 8 test cases cover:
- Reports ready for review
- Approximate date and time
- Unclear safety observations
- Missing workplace locations
- Vague workplace locations
- Missing dates
- Missing times
- Multiple missing fields and rule priority

Run the business rule test script:

```powershell
python -m pytest test_script.py -v
```

These tests run offline without calling Groq or requiring an API key.

### Complete Test Suite

Run all automated tests:

```powershell
python -m pytest tests test_script.py -q
```

The complete suite checks input validation, AI response handling, business rules, JSON persistence, and application workflows.

### Individual Manager Tests

To test a specific module:

```powershell
python -m pytest tests/test_ai_manager.py -v
python -m pytest tests/test_io_manager.py -v
python -m pytest tests/test_main.py -v
python -m pytest tests/test_web_app.py -v
```

The automated tests use simulated AI responses rather than making live Groq API requests.

To Run the AI manager tests in Docker:

```sh
docker compose run --rm --entrypoint python safereport tests/test_ai_manager.py
```
