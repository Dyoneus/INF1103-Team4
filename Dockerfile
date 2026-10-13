FROM python:3.12-slim

# Write AI results to the persistent data mount when running in Docker.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AI_OUTPUT_PATH=/data/ai_output.json

WORKDIR /app

COPY requirements.txt .
# Run the app as a dedicated non-root user and prepare its persistent data paths.
RUN pip install --no-cache-dir -r requirements.txt \
    && addgroup --system app \
    && adduser --system --ingroup app --home /app app \
    && mkdir -p /app/reports /data \
    && chown -R app:app /app /data

COPY --chown=app:app . .

USER app

# Keep submitted reports/photos and AI results outside the container lifecycle.
VOLUME ["/app/reports", "/data"]

CMD ["python", "io_manager.py"]
