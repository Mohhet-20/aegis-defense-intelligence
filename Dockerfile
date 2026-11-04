# AEGIS public demo -- frontend and backend in ONE container, free to host.
#
#   docker build -t aegis-demo .
#   docker run --rm -p 7860:7860 aegis-demo        # then open http://localhost:7860
#
# Runs on a free Hugging Face Space (Docker SDK), a free Render web service, or anything
# that runs a container -- see docs/operations/PUBLIC_DEMO.md. Every start loads fresh
# synthetic demo data (and again every DEMO_RESET_HOURS), with the real pretrained
# detector and a real-photo evaluation preloaded. For a real deployment use
# docker-compose.yml (PostgreSQL, nginx, persistent volumes) instead.

# ---- 1. frontend build ---------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Map tiles: OpenStreetMap's public servers are fine for a low-traffic demo under the OSMF
# tile usage policy (attribution shown on the map). Pass an empty value to disable tiles.
ARG VITE_MAP_TILE_URL=https://tile.openstreetmap.org/{z}/{x}/{y}.png
ARG VITE_MAP_TILE_ATTRIBUTION="&copy; OpenStreetMap contributors"
ENV VITE_MAP_TILE_URL=$VITE_MAP_TILE_URL VITE_MAP_TILE_ATTRIBUTION=$VITE_MAP_TILE_ATTRIBUTION
# The exact Content-Security-Policy nginx would serve (frontend/nginx.conf + tile host).
RUN npm run build \
 && node --input-type=module -e "import {previewCsp} from './deploy/csp.mjs'; process.stdout.write(previewCsp('nginx.conf', process.env.VITE_MAP_TILE_URL))" > /web/csp.txt

# ---- 2. backend + built frontend ---------------------------------------------------------
FROM python:3.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# Hugging Face Spaces run containers as uid 1000.
RUN useradd --create-home --uid 1000 aegis \
 && mkdir -p /app/backend /app/frontend /app/models /app/eval_data /data \
 && chown -R aegis:aegis /app /data
WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY --chown=aegis:aegis backend/ ./
COPY --from=web --chown=aegis:aegis /web/dist /app/frontend/dist
COPY --from=web --chown=aegis:aegis /web/csp.txt /app/frontend/csp.txt

USER aegis
ENV CV_MODEL_DIR=/app/models CV_EVAL_DATA_DIR=/app/eval_data
# Real detector weights (SHA-256 pinned) and the 200-photo COCO evaluation sample, baked
# into the image so the demo needs no downloads at start. FETCH_EVAL_DATA=0 skips the
# sample (the real-image evaluation is then unavailable; the detector still works).
ARG FETCH_EVAL_DATA=1
RUN python scripts/fetch_models.py \
 && if [ "$FETCH_EVAL_DATA" = "1" ]; then python scripts/fetch_eval_data.py; fi

# Public-demo configuration. All data is synthetic and thrown away on every reset.
#   SECRET_KEY        generated per start unless you set one (sessions end on restart)
#   TRUSTED_PROXY_HOPS  proxies in front of the container that append X-Forwarded-For
#   FRONTEND_FRAME_ANCESTORS  lets the Hugging Face Space page embed the app
ENV ENVIRONMENT=production \
    DEMO_MODE=true \
    DEMO_RESET_HOURS=6 \
    DATABASE_URL=sqlite:////data/aegis-demo.db \
    CV_MEDIA_STORAGE_ROOT=/data/media \
    FRONTEND_DIST_DIR=/app/frontend/dist \
    FRONTEND_CSP_FILE=/app/frontend/csp.txt \
    FRONTEND_FRAME_ANCESTORS=https://huggingface.co \
    TRUST_FORWARDED_HEADERS=true \
    TRUSTED_PROXY_HOPS=1 \
    RATE_LIMIT_AUTH=30/minute \
    ENABLE_API_DOCS=true \
    CORS_ALLOWED_ORIGINS= \
    PORT=7860

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 \
  CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"7860\")}/api/v1/health/live', timeout=4).status == 200 else 1)"

# Resets and seeds the demo database, starts uvicorn, loads the demo walkthrough.
CMD ["python", "scripts/demo_server.py"]
