# Backup and restore

Tool: `backend/scripts/backup_restore.py` (SQLite via the online-backup API; PostgreSQL via `pg_dump -Fc` / `pg_restore`, which must be on `PATH`).

## What is backed up
One directory containing the database dump, every file under the private storage root (`CV_MEDIA_STORAGE_ROOT`: uploaded media, `reports/` artifacts, anything else stored there) with SHA-256 each, and `manifest.json` (alembic revision, engine, per-table row counts, file list). **Not included:** `.env` and secrets (use your secret manager), logs, the frontend build, the edge devices' own local stores. If `REPORT_STORAGE_ROOT` is set outside the storage root the script refuses to run (report artifacts would be missed): leave it unset or back that directory up separately.

## Procedure
1. Pause writes (stop the backend or put the proxy in maintenance). The database and the files reference each other; the script re-hashes the files after the database copy and **fails** if anything changed meanwhile.
2. `python scripts/backup_restore.py backup --dest /backups/aegis-$(date +%F)` (uses `DATABASE_URL` and `CV_MEDIA_STORAGE_ROOT` from the environment; override with `--db-url` / `--storage-root`). The destination must be empty.
3. `python scripts/backup_restore.py verify --backup /backups/aegis-YYYY-MM-DD` (re-hashes everything).
4. Copy the directory off the host; protect it like the live data (it contains evidence and user records, including password hashes).
5. **Test a restore** somewhere disposable before trusting a backup (below). Schedule this; the script does not schedule itself (use cron/systemd timers and your own retention for old backups; AEGIS never deletes backups).

## Restore
`python scripts/backup_restore.py restore --backup DIR --target-db-url URL --target-files DIR`
- Refuses to overwrite: the target SQLite file must not exist / the PostgreSQL database must have no tables, and the target files directory must be empty or absent. Create an empty database first (`createdb`).
- Same engine only (SQLite→SQLite, PostgreSQL→PostgreSQL).
- Afterwards it re-verifies every file hash, every table's row count and the alembic revision against the manifest, and exits non-zero on any difference.
- To restore **over** a live installation, stop the app, move the old data aside (do not delete it), restore into the empty locations, point `DATABASE_URL`/`CV_MEDIA_STORAGE_ROOT` at them, start, and run the smoke test.
- If the running code is newer than the backup's revision, run `alembic upgrade head` after restoring; if it is older, deploy the matching release.

## What was tested (this repository, synthetic data, disposable locations)
- SQLite, automated (`tests/test_release_backup_restore.py`): bootstrap admin, ingest 3 events, upload an image, create an investigation and a report → backup → verify → restore elsewhere → the application logs in against the restored database, lists the same events, downloads the byte-identical image and the report whose SHA-256 matches. Also: tampered/missing backup file detected, restore refuses non-empty targets and leaves them untouched, backup fails when files change mid-run, manifest contains no secrets.
- PostgreSQL 16, manual: backup → verify → restore into a new empty database with `pg_restore`; row counts, files and revision matched the manifest; a second restore into the now non-empty database was refused; the application read the restored records (login + model list).
- **Not tested:** very large datasets, point-in-time recovery / WAL archiving, restoring to a different PostgreSQL major version, restore of a backup taken while writes were running, backup encryption (encrypt the backup directory yourself).

## Retention and archival
Backups: yours to manage. Application data: no automatic deletion of evidence; report artifacts expire per `REPORT_RETENTION_DAYS` (run record kept, file removed on read or via the admin purge endpoint); other lifecycle deletions go through two-person `/lifecycle/requests` and per-policy `LIFECYCLE_*` settings; `AUDIT_RETENTION_DAYS=0` means audit records are kept indefinitely.
