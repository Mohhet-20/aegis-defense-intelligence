# AEGIS deployment guide

AEGIS is a **modular monolith**: one FastAPI process (`backend/app/main.py`), one SQL database, one private file root, and a static React build. It is a defensive, human-supervised decision-support application; nothing here adds autonomous targeting or weapon control.

## Supported deployment modes (and their verification status)
| Mode | Status | Notes |
|---|---|---|
| Native development: SQLite + `uvicorn` + `vite` | **Verified** (daily use, full test suite) | `ENVIRONMENT=development`, demo accounts from `scripts/seed.py`. |
| Native single host, PostgreSQL 16, `ENVIRONMENT=production` | **Verified** on a disposable local PostgreSQL 16 (migrations, smoke test 23/23, restart, graceful SIGTERM). Not verified behind TLS/reverse proxy. | Recommended for real use. |
| `docker compose` (PostgreSQL + backend + nginx) | **Not verified**: images could not be built in the authoring environment (Docker Hub unreachable). `docker compose config` validates. | Treat as a starting point; run the smoke test against it before relying on it. |
| Public demo: one container (root `Dockerfile`, `DEMO_MODE`) | **Verified outside Docker** with the image's settings; image build runs in CI | Showcase only -- synthetic data, reset every few hours, free hosting. See [`PUBLIC_DEMO.md`](PUBLIC_DEMO.md). Never for real data. |
| Kubernetes / multi-node / HA / horizontal scale | **Not implemented, not supported** | Jobs are synchronous in-request, rate limiting and metrics are per-process, files are on local disk. Run **one** backend process group per database+storage pair. |

Supported runtimes: Python 3.12+ (3.13 in CI and the Docker image; 3.14 verified natively on Windows 11; 3.11 is **not** supported -- `numpy==2.5.4` needs 3.12), Node.js 20+ (22 in CI/Docker; 24 verified natively), PostgreSQL 16 (production), SQLite (development/test only). No GPU or model weights are required; the bundled adapters are a deterministic mock detector and an OpenCV HOG person detector (`opencv-python-headless`).

## Architecture and data flow
```
Browser ── HTTPS ──> reverse proxy / nginx (static SPA, same-origin /api proxy)
                         │ /api/v1/*
                         ▼
                FastAPI (uvicorn) ──> SQLAlchemy ──> PostgreSQL (SQLite in dev)
                         │
                         ├──> private storage root (CV_MEDIA_STORAGE_ROOT): uploaded media, reports/ artifacts
                         ├──> in-process model adapters (mock / OpenCV HOG), tracker and analytics runtimes
                         └──> optional, off by default: copilot provider (COPILOT_PROVIDER=none), embeddings
Edge devices ── X-Device-Id / X-Device-Api-Key ──> /api/v1/edge/*  (separate device authentication)
```
- Authentication: JWT access/refresh tokens (`/auth`), roles and permissions in `app/core/security.py`; every record is scoped to the caller's `organization_id` (foreign/missing records return 404).
- Jobs (ingestion, inference, tracking, reports, sync) run **synchronously inside the request**; there is no queue, worker or cancellation of running work. Status values are terminal when the request returns.
- Files are never served statically; they are read through authenticated routes that check tenant ownership.
- Optional external network use: only if you set `COPILOT_PROVIDER`/`COPILOT_ALLOW_EXTERNAL` or connectors; defaults send nothing outside.

## Prerequisites
Python 3.12+ (3.13 recommended) with `pip`, Node 20+ (22 recommended) with `npm`, PostgreSQL 16 client tools (`pg_dump`, `pg_restore`) for backups, a TLS-terminating reverse proxy for any non-local use, a secret manager or protected `.env` for `SECRET_KEY` and the database password.

## Native development
```
cd backend
python -m pip install -r requirements.txt
cp .env.example .env                      # development defaults
alembic upgrade head
python scripts/seed.py                    # demo org + accounts (refuses in production)
uvicorn app.main:app --reload --port 8000
# second terminal
cd frontend && npm ci && npm run dev      # Vite proxies /api to localhost:8000
```

## Native production-style (single host, PostgreSQL)
```
export ENVIRONMENT=production
export DATABASE_URL='postgresql+psycopg2://USER:PASSWORD@HOST:5432/aegis'   # URL-encode special characters
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"   # store it; do not regenerate per start
export CORS_ALLOWED_ORIGINS='https://aegis.example.org'
export CV_MEDIA_STORAGE_ROOT=/var/lib/aegis/media        # persistent, backed up, owned by the service user
export CV_MODEL_DIR=/var/lib/aegis/models                # pretrained weights (fetched once, verified on every load)
export LOG_FORMAT=json
cd backend
alembic upgrade head                                      # explicit; never run automatically by the web process
python scripts/fetch_models.py                            # optional: real detector weights (SHA-256 pinned); --from-dir for offline hosts
AEGIS_BOOTSTRAP_PASSWORD='…' python scripts/bootstrap_admin.py --organization "Example Org" --username admin --email admin@example.org
uvicorn app.main:app --host 127.0.0.1 --port 8000         # behind the reverse proxy
curl -s http://127.0.0.1:8000/api/v1/health/ready
AEGIS_SMOKE_PASSWORD='…' python scripts/smoke_test.py --username admin --expect-docs-disabled   # creates a few synthetic rows
cd ../frontend && npm ci && npm run build                 # serve frontend/dist from the proxy with SPA fallback to index.html
```
In production mode the process **refuses to start** with the placeholder or a short `SECRET_KEY` (or a short `SECRET_KEY_PREVIOUS` entry), or with wildcard CORS. Browser sessions use an HttpOnly refresh cookie that is `Secure` in production, so the site must be served over https (set `AUTH_COOKIE_SECURE=false` only for a deliberate plain-http test). Interactive API docs (`/api/docs`) are off unless `ENABLE_API_DOCS=true`. Production defaults for every variable are in `CONFIGURATION_REFERENCE.md`; `GET /api/v1/security/config` (requires the `security:read` permission) shows the startup security review.

Reverse proxy requirements: forward `/api/` to the backend, allow request bodies up to `MAX_UPLOAD_REQUEST_BYTES` (80 MiB default), terminate TLS, set `TRUST_FORWARDED_HEADERS=true` **only** if the proxy overwrites `X-Forwarded-*`, and fall back unknown paths to `index.html`. A reference nginx config is `frontend/nginx.conf`.

## Docker Compose (unverified here)
```
cp .env.example .env          # set AEGIS_DB_PASSWORD and AEGIS_SECRET_KEY (compose refuses to run without them)
docker compose build
docker compose up -d db
docker compose run --rm migrate
docker compose run --rm backend python scripts/fetch_models.py   # optional: weights into the aegis_models volume
docker compose run --rm -e AEGIS_BOOTSTRAP_PASSWORD backend python scripts/bootstrap_admin.py --organization "Example Org" --username admin --email admin@example.org
docker compose up -d
docker compose ps                         # db and backend report healthy
docker compose logs -f backend
AEGIS_SMOKE_PASSWORD=… python backend/scripts/smoke_test.py --base-url http://localhost:8080 --username admin --expect-docs-disabled
docker compose stop                       # graceful (SIGTERM, 30 s); volumes aegis_pg_data, aegis_media and aegis_models persist
```
The `migrate` service is a one-shot job so schema changes are never racing between workers. The frontend image is nginx-unprivileged on 8080; the database is not published to the host.

## Frontend delivery
`npm run build` (= `tsc -b && vite build`) produces `frontend/dist`. API calls use the relative base `/api/v1` (same origin via the proxy), so no backend URL, key or secret is compiled in. The only build-time variables are the public, non-secret map settings `VITE_MAP_TILE_URL` / `VITE_MAP_TILE_ATTRIBUTION` (empty by default = no map tiles, nothing contacted); if you set a tile provider, browsers will contact that host. Source maps are not emitted. Hidden UI controls are conveniences; every permission is enforced by the backend (verified by the authorization sweep tests).

## Limits (defaults; see CONFIGURATION_REFERENCE.md)
Request body 10 MiB (`MAX_REQUEST_BODY_BYTES`), upload request 80 MiB, image 10 MiB / 6000 px, video 75 MiB / 600 s / 30 sampled frames, page size ≤ 200, report window ≤ 366 days with row and size caps, per-process rate limits (`RATE_LIMIT_AUTH`, `RATE_LIMIT_DEFAULT`).
