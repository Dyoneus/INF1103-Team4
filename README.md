# SafeReport

SafeReport is a terminal application for recording workplace safety reports. It validates report details and stores each submitted report and any attached photos as JSON and image files.

## Requirements

- Python 3.12 or later for running locally
- Docker Desktop (or another Docker Engine) for running in a container
- A Groq API key only when using the separate AI analysis script

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

## Configure the AI API

The interactive report-entry application does not call the AI service. `ai_manager.py` is a separate script that analyses JSON reports in `reports/`.

For Docker, copy `.env.example` to `.env` and replace `your_groq_api_key_here` with your Groq API key. Docker reads this file when passed `--env-file .env`. Do not commit `.env`.

For local use, `.env` is not loaded automatically. Set the key in the current shell before running `python ai_manager.py`:

```powershell
$env:GROQ_API_KEY = "your_actual_groq_api_key"
```

On macOS or Linux:

```sh
export GROQ_API_KEY="your_actual_groq_api_key"
```

AI results are written to `ai_output.json` by default. Set `AI_OUTPUT_PATH` to choose a different destination.

## Run with Docker

### Start the report-entry app

Run these commands from the repository root (the folder containing `docker-compose.yml`):

```powershell
docker compose build
docker compose run --rm safereport
```

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
