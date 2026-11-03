# AEGIS backend image (FastAPI + Alembic). Runs as a non-root user and does NOT
# migrate on start: schema changes are a separate, explicit step
# (`alembic upgrade head`, the `migrate` service in docker-compose.yml).
#
# Not production-ready by default on purpose: with ENVIRONMENT=production the app
# refuses to start unless SECRET_KEY is a real secret (app/main.py).
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system --gid 10001 aegis \
 && useradd --system --uid 10001 --gid aegis --home-dir /app --shell /usr/sbin/nologin aegis

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=aegis:aegis . .

# Private storage (uploaded media, report artifacts) lives on a volume, never
# inside the image and never under a served directory.
# Pretrained model weights also live on a volume: fetched once with
# `python scripts/fetch_models.py` and SHA-256-verified on every load.
RUN mkdir -p /data/media /data/models && chown -R aegis:aegis /data
ENV CV_MEDIA_STORAGE_ROOT=/data/media CV_MODEL_DIR=/data/models
VOLUME ["/data/media", "/data/models"]

USER aegis
EXPOSE 8000

# Readiness (database + storage + runtime checks), not just "process is up".
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=4).status == 200 else 1)"

# exec form: uvicorn is PID 1 and receives SIGTERM for graceful shutdown.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
