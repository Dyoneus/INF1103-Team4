# SafeReport

SafeReport is a terminal application for recording workplace safety reports. It validates report details and stores each submitted report and any attached photos as JSON and image files.

## Requirements

- Python 3.12 or later for running locally
- Docker Desktop (or another Docker Engine) for running in a container
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

Both `python main.py` open the same menu:

- **1. Create a new safety report** saves the report and assesses its readiness.
- **2. Retry a failed assessment** lists failed reports. Select a number or reference ID to retry and update that same report.
- **3. Clarify and reassess a saved report** lists incomplete reports and reports needing clarification. Answer the requested questions to update and reassess the same record.
- **0. Exit** closes the application. In report selection, 0 cancels instead.

Clarification answers are saved together before reassessment. Ctrl+C during the questions cancels without saving changes. If AI then fails, the corrections remain saved and option 2 can retry them. Reference IDs, reporter details and attached photos are preserved.

## Configure the AI API

The interactive application calls AI after saving a new report, retrying a failed assessment, or saving clarification answers. A missing API key leaves the report saved with status `AI_FAILED`, ready to retry after configuration.

For Docker, copy `.env.example` to `.env` and replace `your_groq_api_key_here` with your Groq API key. Docker reads this file when passed `--env-file .env`. Do not commit `.env`.

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

To enable AI assessment, configure `.env` as described above and start with `docker compose run --rm --env-file .env safereport`.

The app is interactive. Choose **1. Create a new safety report**, complete the prompts, and let it finish saving before exiting. A report JSON file is created only after a report has been completed and submitted.

### Where the files go

Compose connects folders on your computer to folders inside the container:

| On your computer | Inside the container | Contents |
|---|---|---|
| `reports/` | `/app/reports` | Submitted report JSON files and copied photos |
| `data/` | `/data` | AI analysis results, including `ai_output.json` |

This is a **bind mount**: the container writes directly into these project folders. Files remain on your computer after the container exits, even though `--rm` removes the temporary container. Docker creates the host folders if they do not already exist.

If you do not see a new report, check that you ran the command from the repository root and completed report submission. Then refresh the `reports/` folder in your editor or File Explorer.

To run the AI analysis script in Docker, copy `.env.example` to `.env`, set a valid Groq API key, and run:

```sh
docker compose run --rm --env-file .env safereport python ai_manager.py
```

This AI step is separate from entering a report and requires a valid API key. It reads JSON report files from `reports/` and writes analysis results to `data/ai_output.json`. The report and result directories may contain personal or sensitive data. Keep them private and do not commit them.

Use the Compose commands above if you want files to appear in the project folders. If you run the image directly with `docker run` and mount a **named volume** at `/app/reports`, Docker keeps the files in its own managed storage; they will persist, but they will not appear in the project’s local `reports/` folder.

## Tests

Run the complete test suite (AI calls are mocked):

```sh
python -m pytest -q
```

Run the AI manager tests locally:

```sh
python tests/test_ai_manager.py
```

The AI manager test file uses plain functions and a small built-in runner, so run it directly rather than using `unittest discover`.

The separate `test_io_manager.py` file uses pytest-style test functions. If `pytest` is installed, run those with:

```sh
python -m pytest tests/test_io_manager.py
```

Run the AI manager tests in Docker:

```sh
docker compose run --rm --entrypoint python safereport tests/test_ai_manager.py
```
