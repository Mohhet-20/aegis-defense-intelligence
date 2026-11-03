# Administrator guide

## First login and accounts
Fresh deployments have no accounts. Create the first organization and administrator once (after `alembic upgrade head`):
`AEGIS_BOOTSTRAP_PASSWORD='…' python backend/scripts/bootstrap_admin.py --organization "…" --username admin --email …`
(password policy applies; the script refuses if the organization already has an administrator; it writes a `user.bootstrap_admin` audit record). Further users: `/users` API/UI as an administrator. The demo accounts from `scripts/seed.py` use a published password and the script refuses to run when `ENVIRONMENT=production`.

## Secrets
- `SECRET_KEY` (JWT signing) and the database password live only in the environment / secret manager. Never commit `.env`. The compose file reads `.env`; the app refuses to start in production with a placeholder or short key.
- **Rotating `SECRET_KEY`:** generate a new value (`python -c "import secrets;print(secrets.token_urlsafe(48))"`), move the old value to `SECRET_KEY_PREVIOUS`, set the new one as `SECRET_KEY`, restart. New tokens are signed with the new key; tokens issued before the rotation keep working until they expire. After `REFRESH_TOKEN_EXPIRE_MINUTES` (default 7 days) remove the old key from `SECRET_KEY_PREVIOUS` and restart again. If the old key was compromised, skip the grace period: leave `SECRET_KEY_PREVIOUS` empty so every existing token is rejected and everyone signs in again. Passwords, data and device keys are unaffected. To force a single user out use `/auth/revoke-sessions` (self) or `POST /api/v1/users/{id}/revoke-sessions` (administrator).
- **Rotating a device key:** `POST /api/v1/devices/{id}/rotate-key` (old key stops working immediately).
- **Rotating the database password:** change it in PostgreSQL, update `DATABASE_URL`, restart the backend.
- If a secret was ever committed or logged, treat it as exposed and rotate it; deleting the file does not remove it from git history.

## Storage
All uploads and report artifacts are under `CV_MEDIA_STORAGE_ROOT` (container: `/data/media` on volume `aegis_media`): private, outside any served directory, accessed only through authenticated tenant-checked routes. Check free space regularly (`df -h`); `/health/ready` verifies the root is writable, not that it has capacity. Back up database and storage together (`BACKUP_AND_RESTORE.md`). Retention: reports expire after `REPORT_RETENTION_DAYS`; other deletions go through `/lifecycle/requests` (two-person approval when `LIFECYCLE_REQUIRE_SEPARATE_APPROVER=true`); evidence is never auto-deleted.

## Monitoring (what actually exists)
- Liveness `GET /api/v1/health/live`; readiness `GET /api/v1/health/ready` (database, media storage, model, tracker and sensor-analytics runtimes). Both are unauthenticated and reveal only ok/error per check.
- Authenticated (permission `observability:read`): `GET /api/v1/observability/summary`, `/metrics` (JSON), `/metrics/prometheus`, `/health`. These metrics are **per process and reset on restart**; there is no persistent time series, alerting, or host/disk metric — use your own monitoring for disk, CPU, memory and PostgreSQL.
- Logs: `LOG_FORMAT=json` gives one JSON object per line (timestamp, severity, subsystem, request_id, method, path, status_code, duration_ms, outcome, error_category). A redaction filter masks bearer tokens, JWTs, passwords and similar fields. Audit trail: `GET /api/v1/audit` (administrators); append-only by convention, **not tamper-proof**.

## Upgrades and recovery
`RUNBOOKS.md` §14 (upgrade), §15 (rollback), §13 (restore). Always backup + verify first; migrations are an explicit step, never run by the web process.

## Hardening checklist before exposing the service
TLS at the proxy; `ENVIRONMENT=production`; strong `SECRET_KEY`; explicit https `CORS_ALLOWED_ORIGINS`; PostgreSQL with a dedicated least-privilege role; storage directory owned by the service user (mode 0750); `ENABLE_API_DOCS` unset; `TRUST_FORWARDED_HEADERS` true only behind a trusted proxy; review `GET /api/v1/security/config`; run `backend/scripts/security_checks.py`; confirm a restore test passed.
