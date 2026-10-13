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
python io_manager.py
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

Build the image from the repository root:

```sh
docker build -t safereport .
```

Create named volumes once. The first stores reports and attached photos; the second stores AI results:

```sh
docker volume create safereport-reports
docker volume create safereport-results
```

Start the interactive report-entry application:

```sh
docker run --rm -it --mount type=volume,source=safereport-reports,target=/app/reports safereport
```

Reports and photos in `safereport-reports` remain available after the container exits or is removed. To list or inspect them, use `docker volume inspect safereport-reports`.

To run the AI analysis script in Docker, ensure reports are present in the reports volume and `.env` contains a valid API key:

```sh
docker run --rm --mount type=volume,source=safereport-reports,target=/app/reports --mount type=volume,source=safereport-results,target=/data --env-file .env safereport python ai_manager.py
```

The results volume keeps `/data/ai_output.json` available across runs. Protect both volumes as they may contain personal or sensitive report data. Remove a volume only when you intentionally want to delete its stored data:

```sh
docker volume rm safereport-reports
docker volume rm safereport-results
```

## Tests

Run the complete test suite locally:

```sh
python -m unittest discover -s tests -v
```

Run the same suite in the built image:

```sh
docker run --rm --entrypoint python safereport -m unittest discover -s tests -v
```
