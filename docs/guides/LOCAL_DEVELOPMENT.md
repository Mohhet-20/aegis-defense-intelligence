# Local development guide

The README's quick start is the short version. This page covers versions, configuration,
alternative ports, the demo data and the problems people actually hit.

## Supported versions

| Component | Supported | Verified |
|---|---|---|
| Python | 3.12+ | 3.14.4 on Windows 11 (clean venv install + full test suite); 3.12/3.13 only in the CI matrix (authored, not yet executed); the Docker image uses 3.13 |
| Node.js | 20+ (`engines` in `frontend/package.json`) | 24.18 on Windows 11; 22 in CI and the Docker image |
| Database | SQLite (development/test), PostgreSQL 16 (production) | Both on Windows 11: full suite on SQLite and on PostgreSQL 16.10 (portable binaries, non-UTC server zone), migrations, production smoke, backup/restore |

To test against PostgreSQL without installing a service, the official EDB "binaries" ZIP for Windows
works: `initdb -D <dir> -U aegis -W`, `postgres -D <dir> -p 55432`, `createdb aegis_test`, then set
`TEST_DATABASE_URL` (see `docs/testing/INTEGRATION_TESTING.md`). Use a throwaway data directory.

Python 3.11 is **not** supported: `pip install -r requirements.txt` fails because `numpy==2.5.4`
requires Python 3.12. On Python 3.14, `psycopg2-binary` must be 2.9.11 or later (2.9.10 has no
3.14 wheel and tries to compile); `requirements.txt` pins 2.9.11.

`opencv-python-headless` is pinned to the 4.x line on purpose: 5.0 removed `cv2.HOGDescriptor`,
which the HOG person detector and the `/health/ready` model-runtime check need. Verify with
`python -c "import cv2; print(cv2.__version__, hasattr(cv2, 'HOGDescriptor'))"` → `4.14.0 True`.

## Configuration

- `backend/.env.example` → copy to `backend/.env`. Every default is a safe development value;
  every variable is listed in `docs/operations/CONFIGURATION_REFERENCE.md` (generated from
  `app/core/config.py`; `python scripts/gen_config_reference.py` regenerates it).
- `frontend/.env.example` → optional `frontend/.env`:
  - `VITE_MAP_TILE_URL` -- map tiles for the Map Explorer. Empty by default: no tile provider is
    contacted and the map shows a fallback card plus an accessible list. See
    `docs/operations/MAP_PROVIDER_CONFIGURATION.md` before setting it (tile requests go from
    the browser to that host).
  - `AEGIS_DEV_API_TARGET` -- where `npm run dev` / `npm run preview` proxy `/api`
    (default `http://localhost:8000`). Dev-server only; never included in the bundle.
- Never commit `.env` files (both are git-ignored).

## Running on other ports

```bash
uvicorn app.main:app --reload --port 8010                       # backend
AEGIS_DEV_API_TARGET=http://127.0.0.1:8010 npm run dev           # frontend, bash
```

PowerShell: `$env:AEGIS_DEV_API_TARGET = "http://127.0.0.1:8010"; npm run dev`.

If the browser talks to the backend directly (not through the Vite proxy), add its origin to
`CORS_ALLOWED_ORIGINS` in `backend/.env`.

## Database lifecycle

- Always `alembic upgrade head` first. `scripts/seed.py` refuses to run on a database that is not
  at the migration head (it used to create tables itself, which broke later migrations).
- After pulling new code, run `alembic upgrade head` again. Upgrading an existing development
  database schema (`a14c0de5ec01`) to head (`c16r3p0rt01`) was tested on a
  copy of a real local database: all rows preserved.
- `alembic check` on a migrated database must report "No new upgrade operations detected".
- To start fresh, use a new SQLite file (`DATABASE_URL=sqlite:///./aegis-fresh.db`) or delete the
  development `backend/aegis.db`. Do not delete `media_storage/` contents that a kept database
  still references.

## Demo data

| Command | Creates |
|---|---|
| `python scripts/seed.py` | 1 organization, 4 development accounts (password `DevPassword123!`), synthetic events/assets/sensors/observations, anomalies, spatial relationship candidates, the mock, HOG and SSD-MobileNet CV model records |
| `python scripts/demo_walkthrough.py` | an end-to-end `[DEMO]` dataset through the public API (see README); run it as often as you like |
| `python scripts/fetch_models.py` | the real SSD-MobileNet weights in `CV_MODEL_DIR` (default `backend/model_artifacts/`), SHA-256 verified; `--check` verifies, `--from-dir` installs offline |
| `python scripts/fetch_eval_data.py` | 200 COCO val2017 photos + labels in `CV_EVAL_DATA_DIR` (default `backend/eval_data/`) for real-image evaluation; `--count`, `--seed` |

All of it is synthetic. Seeded records carry `data_origin = synthetic_demo`; walkthrough events
arrive by file upload, so their origin badge reads "file upload" (how they entered, not a claim
about their content) and their titles start with `[DEMO]`.

## Windows notes

- Activate the venv with `.\.venv\Scripts\Activate.ps1` (PowerShell) or
  `.venv\Scripts\activate.bat` (cmd). If script execution is blocked:
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- One-command environment variables: PowerShell has no `VAR=value command` form. Use
  `$env:NAME = "value"` on its own line, then run the command.
- SQLite URLs use forward slashes even on Windows: `sqlite:///./aegis.db`,
  `sqlite:///C:/data/aegis.db`.
- Vite listens on `localhost` (IPv6 `::1` on recent Windows/Node). Use
  `http://localhost:5173`, not `http://127.0.0.1:5173`.
- Console encoding: scripts that print non-ASCII characters may need
  `$env:PYTHONIOENCODING = "utf-8"` in older terminals.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Refusing to seed: database revision ... is not the migration head` | Run `alembic upgrade head`, then seed again. |
| Sidebar says "Database unreachable" | Backend not running on the proxied port, or the schema was never migrated. Check `curl http://127.0.0.1:8000/api/v1/health/ready`. |
| Login says "Too many requests" | Login and password change allow `RATE_LIMIT_AUTH` (default 10/minute) per client address; session refresh has its own `RATE_LIMIT_REFRESH` (120/minute). Wait a minute. |
| Signed out after every reload | The refresh cookie is `Secure` in production and is dropped on plain http. Serve over https, or set `AUTH_COOKIE_SECURE=false` for a deliberate local test. |
| Detection job fails "adapter is not available" for ssd-mobilenet | Weights not installed or modified: `python scripts/fetch_models.py` (then `--check`). |
| Real-image evaluation returns 409 | The COCO subset is not installed: `python scripts/fetch_eval_data.py`. |
| "Account temporarily locked" | 5 failed logins lock an account for 15 minutes (`MAX_FAILED_LOGIN_ATTEMPTS`, `ACCOUNT_LOCKOUT_MINUTES`). Wait, or use a fresh development database. |
| `Refusing to start ... SECRET_KEY` | `ENVIRONMENT=production` requires a random `SECRET_KEY` of at least 32 characters: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| CORS errors in the browser console | The page origin is not in `CORS_ALLOWED_ORIGINS` (comma-separated). |
| `resolves to a disallowed address` when running an HTTP source | The connector SSRF guard (`app/connectors/url_safety.py`) blocks private/loopback targets unless a development source explicitly sets `allow_local_dev`. |
| Map Explorer shows no tiles | `VITE_MAP_TILE_URL` is empty by design; see Configuration above. |
| `pip install` fails building `psycopg2-binary` or finding `numpy==2.5.4` | Python version: see Supported versions. |

Operational failures (disk, migrations, storage, restore) are covered in
`docs/operations/RUNBOOKS.md`.
