# Operational runbooks

Conventions: commands assume a Linux host and a native deployment (`systemctl`/shell); for Docker Compose substitute `docker compose logs backend`, `docker compose exec backend …`. None of these runbooks starts by deleting data. Health: `curl -s localhost:8000/api/v1/health/live` (process) and `/ready` (database, storage, model/tracker/sensor runtimes; 503 names the failing check as `"error"`).

## 1. Application will not start
**Symptoms:** process exits immediately. **Diagnose:** read the first error in the log. `Refusing to start: ENVIRONMENT=production but SECRET_KEY…` / `Refusing to start in production: …` = configuration review blocker (placeholder or <32-char secret, wildcard CORS). `ModuleNotFoundError` = dependencies not installed for this Python (3.13). `OperationalError` = see §2. **Recover:** fix the setting (see `CONFIGURATION_REFERENCE.md`), restart. **Data loss:** none. **Verify:** `/health/ready` is 200.

## 2. Database connection failure
**Symptoms:** `/ready` 503 with `"database": "error"`; 500s with "An internal error occurred" and `unhandled_exception` in logs. **Diagnose:** `pg_isready -h HOST -p 5432`; `psql "$DATABASE_URL_WITHOUT_DRIVER_SUFFIX" -c 'select 1'`; check disk space and connection limits on the database host. **Causes:** database down, wrong credentials/host (special characters in the password must be URL-encoded), network/firewall, exhausted connections. **Recover:** restore the database service, correct `DATABASE_URL`, restart the backend. **Data loss:** none from the connection failure itself; in-flight requests failed and can be retried (ingestion de-duplicates by external id). **Verify:** `/ready` 200, smoke test.

## 3. Migration failure
**Symptoms:** `alembic upgrade head` errors part-way. **Before any upgrade:** take a verified backup (BACKUP_AND_RESTORE.md). **Diagnose:** `alembic current`, `alembic heads` (must be one head), the error text; PostgreSQL migrations are transactional per revision but SQLite batch operations are not. **Recover:** fix the cause (permissions, locks held by other sessions, pre-existing conflicting data — the migration logs and skips the unique index when duplicate model rows exist) and re-run `alembic upgrade head`; it resumes from the last applied revision. If the schema is inconsistent and cannot be repaired, restore the pre-upgrade backup into a new empty database and redeploy the previous release. `alembic downgrade -1` exists for every revision but may drop columns/tables created by that revision — use only after a backup. **Never** drop or recreate the production database to "make the migration pass." **Verify:** `alembic current` shows the head, `scripts/smoke_test.py` passes.

## 4. Authentication configuration failure
**Symptoms:** everyone gets 401 after a restart; or startup refused. **Causes:** `SECRET_KEY` changed (all tokens become invalid — expected; users log in again), clock skew, locked account (`MAX_FAILED_LOGIN_ATTEMPTS`, `ACCOUNT_LOCKOUT_MINUTES`), rate limit on `/auth` (`RATE_LIMIT_AUTH`). **Diagnose:** log lines for `auth` events (no secrets are logged); `GET /api/v1/audit` as an administrator. **Recover:** restore the correct `SECRET_KEY` from the secret manager if it changed by accident; an administrator can use `POST /api/v1/users/{id}/reset-password` or PATCH `/users/{id}`. No administrator at all (fresh deployment): `scripts/bootstrap_admin.py`; if the only administrator is lost, create a new organization+administrator with the same script under a new organization name (it refuses to add a second admin to an organization that has one). **Data loss:** none.

## 5. Missing model artifacts / inference runtime failure
**Symptoms:** `/ready` `"model_runtime": "error"`; inference jobs finish `failed` with a sanitized `error_message`; MLOps artifact verification reports a mismatch. **Diagnose:** `GET /api/v1/cv-models`, `POST /api/v1/mlops/models/{id}/verify-artifact`, backend log (`operation`/`error_category` fields). **Causes:** model record points to an adapter key that is not registered, artifact file moved/changed (digest mismatch), OpenCV missing. **Recover:** register a valid model version (registered versions are immutable), restore the artifact from backup, reinstall `opencv-python-headless`. Failed jobs can be retried (`POST /inference/jobs/{id}/retry`, bounded); completed jobs cannot. **Data loss:** none; failed jobs produce no detections.

## 6. Upload or storage failure
**Symptoms:** uploads return 4xx/5xx; `/ready` `"media_storage": "error"`; 413 from the proxy. **Diagnose:** `df -h` and `ls -ld` on the storage root; the service user can write there; proxy `client_max_body_size` ≥ 80 MiB (`frontend/nginx.conf` sets it). **Causes:** disk full, wrong ownership (container runs as UID 10001), storage volume not mounted, file larger than `CV_MAX_*_UPLOAD_BYTES`. **Recover:** free space by moving old backups/logs (not evidence), fix ownership/mount, restart. Files are written to storage before the database row is committed (rejected videos are removed immediately), so a crash between the two can leave an unreferenced file; list them with `python scripts/sweep_orphan_files.py` (report only; covers media and report artifacts, ignores files younger than 24 h), take a backup, then re-run with `--delete` if the list is what you expect. **Verify:** upload a small image via the smoke test.

## 7. Background-job failure
There is no worker. Jobs run in the request; a crash or timeout leaves the request failed and the job row in its last written state (`failed` after an error; scenario runs have `SCENARIO_STALE_RUN_SECONDS` stale detection). **Diagnose:** the job's list endpoint (`/ingestion/jobs`, `/inference/jobs`, `/tracking/jobs`, `/scenario-runs`), logs by `request_id`/`job_id`. **Recover:** use the job's retry endpoint where it exists; re-submit otherwise. **Data loss:** partial ingestion batches report accepted/duplicate/rejected counts per record; re-uploading is safe because duplicates are detected.

## 8. Report-generation failure
**Symptoms:** report status `failed` (never shown as a success), `report.generation_failed` audit action; download 409 with `report.integrity_mismatch` means the stored file no longer matches its recorded SHA-256. **Diagnose:** `GET /api/v1/reporting/reports/{id}` (sanitized reason), audit log, free disk. **Recover:** fix cause (window too large — max 366 days —, disk, storage permissions) and generate again; for an integrity mismatch restore `reports/` from backup or regenerate. Expired reports are not recoverable except from backup. **Data loss:** artifacts only.

## 9. Disk-space exhaustion
**Symptoms:** `/ready` storage error, database write errors, PostgreSQL panics. **Diagnose:** `df -h`; `du -sh <storage root>/* | sort -h | tail`; database size. **Recover:** extend the volume, or move **copies** of old backups/log files off-host; reduce growth with documented retention (`REPORT_RETENTION_DAYS`, `/lifecycle` requests). Do not delete media, evidence, reports or database files as a first response. **Verify:** `/ready` 200; run a backup + verify.

## 10. Configuration mistakes
Compare effective settings with `CONFIGURATION_REFERENCE.md`; `GET /api/v1/security/config` lists security findings with severities. Typical: CORS origin missing the scheme/port (browser blocks calls), `TRUST_FORWARDED_HEADERS` true without a trusted proxy (spoofable client IPs in audit/rate limits), SQLite in production, storage root on ephemeral disk.

## 11. Dependency outage
Only the database and the storage root are hard dependencies. Optional providers (copilot, embeddings) fail safely: with `COPILOT_PROVIDER=none` (default) nothing external is called; with a provider enabled, outages produce a degraded answer/error, not a startup failure. Check `COPILOT_*` settings before blaming the platform.

## 12. Unexpected shutdown
Restart; migrations are not needed unless you upgraded. In-flight requests at crash time are lost; check the last job rows (§7) and the audit log for the final recorded actions. For PostgreSQL rely on its own crash recovery; for SQLite run `PRAGMA integrity_check` on a copy. Verify with `/ready` and the smoke test.

## 13. Restore from backup
See `BACKUP_AND_RESTORE.md`. Summary: stop app → restore into empty locations → point config at them → `alembic upgrade head` if the code is newer → start → smoke test → keep the old data aside until satisfied.

## 14. Safe upgrade
1) Read the release notes (`CHANGELOG.md`). 2) Backup + verify. 3) Stop the backend. 4) Deploy the new code/image. 5) `alembic upgrade head` (once). 6) Start. 7) `/health/ready`, smoke test. 8) Keep the backup until the next verified backup.

## 15. Rollback after a failed release
If **no migration ran**: redeploy the previous code. If a migration ran: restore the pre-upgrade backup into a new empty database and storage location and redeploy the previous code against it (data written since the backup is lost — export anything critical first). `alembic downgrade` is a last resort and only after a backup. Verify with the smoke test.
