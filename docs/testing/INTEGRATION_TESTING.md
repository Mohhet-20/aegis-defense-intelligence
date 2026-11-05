# Integration, reliability and CI

## Commands (run from `backend/` unless noted)
```
python -m pytest -q                          # whole suite (~4 min serial; add -n4 if pytest-xdist is installed)
python -m pytest -q tests/test_integration_workflows.py   # workflows A-H
python -m pytest -q tests/test_integration_sweeps.py tests/test_frontend_contract.py
python -m pytest -q --cov=app --cov-report=term
ruff check --select E9,F63,F7,F82 app tests scripts      # the CI lint gate
python scripts/security_checks.py            # migration validation + npm audit; skips tools not installed
python scripts/benchmark_queries.py --events 20000 --runs 5   # disposable in-memory DB; prints hardware + dataset
cd ../frontend && npm ci && npm run lint && npm run build     # tsc -b + vite build
```

## What the workflows prove (`test_integration_workflows.py`)
A auth/permissions; B ingestion provenance/duplicates/malformed input; C evidence and relationship review (uncertain ≠ contradicts, audited); D media → mock inference → human review → promotion, tenant-private media; E investigation notes (optimistic concurrency), transition validation, export, foreign-org denial; F MLOps run (idempotent replay) → analytics → report equal; G report lifecycle, authorization, tamper detection; H edge sync idempotency, stale-write conflict, resolution, credential rotation.
They use the real HTTP stack, in-memory SQLite, mock adapters and synthetic data. They do **not** cover PostgreSQL, a real browser (see `backend/scripts/e2e_reporting_browser.py` pages), real model weights or real devices.

## Running the suite against PostgreSQL
```
createdb aegis_test            # a DISPOSABLE database: every table in it is dropped after each test
TEST_DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@127.0.0.1:5432/aegis_test python -m pytest -q
```
Run it serially (do not add pytest-xdist `-n`): every test drops and recreates the tables of that one
database. Measured on Windows 11 with PostgreSQL 16.10: about 39-50 minutes for the whole suite.
Latest result: 1386 passed, 0 failed (2026-10-18, final working tree). Tests that need a real PostgreSQL session (for example the non-UTC
session-timezone check in `test_release_postgres_compat.py`) skip themselves on SQLite.

Run it against a server whose `TimeZone` is **not** UTC at least occasionally: a UTC-only setup hid a
real analytics defect (`to_char()` bucket labels follow the session zone) until this suite ran on a
server configured as `Asia/Calcutta`. `python scripts/check_schema_drift.py` compares a migrated
database with the ORM (0 differences expected).

## Release tooling
`scripts/bootstrap_admin.py`, `scripts/backup_restore.py`, `scripts/smoke_test.py`, `scripts/check_schema_drift.py`, `scripts/gen_config_reference.py`, `scripts/e2e_release_browser.py` (see `docs/operations/`).

## Troubleshooting
- `422` on a device route used to hide a missing-credentials error; it is now 401.
- A stored event with an out-of-range latitude (legacy/direct DB insert) makes `GET /events` fail response validation (KNOWN_RISKS 33). Ingestion rejects such rows.
- Tests must use disposable databases; nothing in the suite reads `DATABASE_URL` except the migration tests, which restore it.

## Measured performance (this machine, SQLite in-memory; see final report for numbers)
Use `scripts/benchmark_queries.py`. Numbers are not a production or PostgreSQL claim.
