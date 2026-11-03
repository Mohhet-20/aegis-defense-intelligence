# Phase 2 -- Definition of Done &amp; Final Engineering Report

This is the one-time completion record for Phase 2 (Phase 2: Advanced
Intelligence Data Platform -- multi-source ingestion, normalization,
provenance, data quality, and event correlation). For the living,
continuously-updated status, see [`../PROJECT_STATUS.md`](../PROJECT_STATUS.md)
instead -- this file is a snapshot of what was true at the end of this phase.

## Definition of Done -- checklist (26 items)

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Existing AEGIS repo inspected before writing code | Done | Phase 1's 12 modules read via `MODULE_CATALOG.md` before extending any of them |
| 2 | Connector architecture with a common interface | Done | `app/connectors/base.py::BaseConnector`, `registry.py` |
| 3 | At least one real network-reaching connector | Done | `app/connectors/http_connector.py`, tested against a local `http.server` mock (never a live external feed -- Section 11 of `../PROJECT_STATUS.md`) |
| 4 | SSRF hardening on any connector-initiated request | Done | `app/connectors/url_safety.py` -- loopback/private/link-local/reserved/multicast blocked, redirect revalidation, credential-in-URL rejection; `tests/test_connectors.py` + `test_security_phase2.py` |
| 5 | Canonical event schema, documented | Done | `docs/data/CANONICAL_EVENT_SCHEMA.md`, `app/models/event.py` |
| 6 | Raw-record provenance preserved for every record, including rejected ones | Done | `app/models/raw_record.py`, `docs/data/DATA_PROVENANCE.md` |
| 7 | Normalization: timestamps, coordinates, severity-&gt;priority, event-type, documented and versioned | Done | `app/services/normalization_service.py`, `docs/data/CANONICAL_EVENT_SCHEMA.md` |
| 8 | Validation engine with structured error/warning codes | Done | `app/services/validation_service.py`, `tests/test_normalization.py` |
| 9 | Ingestion job orchestration (file upload and connector-driven, same engine) | Done | `app/services/ingestion_service.py::_process_batch()` used by both `run_ingestion()` and `run_connector_source()` |
| 10 | Deduplication: in-batch, cross-batch, and DB-constraint backstop | Done | `docs/data/DEDUPLICATION_POLICY.md`; DB race condition closed with a SAVEPOINT, `tests/test_provenance_and_dedup.py::test_concurrent_duplicate_attempt_is_caught_by_the_db_constraint` |
| 11 | Explicit, documented policy for an updated record with the same external id | Done | "ignore and flag, never silently overwrite" -- `docs/data/DEDUPLICATION_POLICY.md`, tested |
| 12 | Event correlation: rule-based, explainable, requires 2+ independent signals | Done | `app/services/correlation_service.py`, `docs/analytics/EVENT_CORRELATION.md`, `tests/test_correlation.py` |
| 13 | Correlation never auto-merges or auto-confirms | Done | `review_status` starts `candidate`, changes only via an explicit `POST .../review` call -- tested |
| 14 | Source reliability as a human-set, reason-required value, separate from validation/confidence/severity/priority/match-strength | Done | `docs/analytics/SOURCE_RELIABILITY.md`'s 6-concept table; `source_service.set_reliability_weight()` raises without a `reason` |
| 15 | Data quality / job-outcome reporting, computed live, never cached | Done | `app/services/quality_service.py`, `docs/api/INGESTION_API.md` |
| 16 | Source enable/disable, config validation, connectivity check | Done | `app/api/routes/sources.py`, `tests/test_quality_and_sources.py` |
| 17 | Expanded `/api/v1` surface for all of the above | Done | `docs/api/INGESTION_API.md` cites every route by file and permission |
| 18 | Permission model extended, least-privilege per role | Done | 5 new `Permission` values in `app/core/security.py`; viewer gets read-only data-quality/correlation, not raw-record or export |
| 19 | Raw-record access gated separately from event/ingestion read | Done | `RAW_RECORD_READ`, tested in `test_provenance_and_dedup.py` and `test_security_phase2.py` |
| 20 | Controlled, bounded, audited export with CSV-injection guarding | Done | `app/services/export_service.py` (`MAX_EXPORT_ROWS=5000`, formula-prefix neutralization), `tests/test_security_phase2.py` |
| 21 | DB migration preserves existing data (no destructive change) | Done | upgrade/downgrade/re-upgrade cycle run against the real dev DB, data intact throughout (Section 6 of `../PROJECT_STATUS.md`) |
| 22 | Frontend data-operations workspace (sources, jobs, quality, correlation, provenance) | Done | `SourcesPage.tsx`, `IngestionJobsPage.tsx`, `JobDetailPage.tsx`, `DataQualityPage.tsx`, `CorrelationPage.tsx`, `EventDetailPage.tsx` provenance/correlation cards |
| 23 | Automated backend tests, actually run | Done | 172 passed (101 new), 93% coverage -- re-run in this final pass, not just earlier in the session |
| 24 | Frontend checks, actually run | Done | `tsc -b --force` clean, `eslint .` 0 new warnings, `npm run build` succeeded -- re-run in this final pass |
| 25 | Documentation updated to match reality, "what this does NOT do" stated explicitly | Done | 7 new docs + README/MODULE_CATALOG/this file, each with an explicit scope-boundary section |
| 26 | Resume-safety: progress synced externally after this report | Done (final sync step follows this report) | zip -&gt; `SendUserFile` -&gt; device bridge to the owner's local folder, per standing instruction |

## Final Engineering Report (17 points)

**1. What was discovered in the working directory at the start of this
phase.** The real Phase 1 deliverable from the previous session: a working
13-model backend, 12-page frontend, 71 passing backend tests, and the
`docs/implementation/PROJECT_STATUS.md` / `MODULE_CATALOG.md` handoff records
describing it accurately. Nothing was missing or had to be reconstructed --
Phase 1's sync-to-local-folder pipeline had done its job. This phase's
connector/normalization/provenance/correlation/quality work was built as a
genuine extension on top of that baseline, per Rule: never re-implement an
existing module from scratch.

**2. Architecture actually implemented.** Still one FastAPI process, one
database, one React SPA -- no new infrastructure component was introduced.
The one new architectural concept is a **connector architecture**
(`app/connectors/`) that cleanly separates "how a batch of raw records gets
fetched/parsed from a specific kind of source" from "what happens to those
records once fetched" (normalization, validation, dedup, provenance,
event-creation) -- the latter is now a single shared engine
(`_process_batch()`) that a file upload and a connector's own `/run` call both
go through identically.

**3. Principal backend modules added or extended.** New: connector registry
(5 connector types: `http_api`, `json`, `csv`, `synthetic_demo`, legacy alias
`synthetic_generator`), normalization service, validation service, correlation
service, data-quality service, export service. Extended: ingestion-job
management (rewritten engine), data-source registry (enable/disable/
reliability/connectivity), event management (export, raw-record lookup,
correlation lookup). 14 modules total now cataloged in `MODULE_CATALOG.md`
(12 from Phase 1, 2 new).

**4. Frontend pages/interactions implemented.** Sources page rewritten with
enable/disable/reliability/validate-config/check-connectivity/run actions; the
ingestion jobs list extended with a source filter and a new job-detail page
(raw records, retry); a new data-quality dashboard page; a new correlation
review page (list, detail, recompute, confirm/reject); the event detail page
extended with provenance and correlated-candidate cards; the events list
extended with an export button and a `data_origin` filter. All of it calls the
real backend -- `npx tsc -b --force` and a production `npm run build` both
succeeded against the actual extended `api/client.ts`, confirming the types
and the real endpoints agree.

**5. Database/migration status.** One new Alembic migration
(`30bdae7e385e_phase2_data_platform_source_extensions_...`), hand-edited after
autogeneration to add `server_default` values so existing rows backfill
correctly. Verified this session, again, in the final pass: upgrade against
the real dev `aegis.db`, confirmed the pre-existing source and 5 pre-existing
events survived with correct defaults, downgrade confirmed clean removal of
the new columns/tables with data otherwise intact, re-upgrade confirmed `head`
reached cleanly.

**6. Connector and SSRF behavior.** `url_safety.py` resolves the target host
via DNS and rejects loopback/private/link-local (covering the
`169.254.169.254` cloud-metadata address)/reserved/multicast/unspecified
addresses unconditionally for an `https` source; `http` is permitted only when
a source's config explicitly sets `allow_local_dev: true` **and** the resolved
host is loopback -- never for any other `http` destination regardless of the
flag. Every redirect hop is independently revalidated (capped at 4 total
requests), and credentials embedded in a URL are rejected outright. Verified
with `tests/test_connectors.py`'s dedicated SSRF test class and
`test_security_phase2.py`'s end-to-end SSRF test through the real `/run` API
route, not just the unit-level `url_safety` functions.

**7. Normalization and validation behavior.** Timestamps: timezone-aware
values convert to UTC as given; naive values are assumed UTC with that
assumption explicitly recorded (`timestamp_policy="assumed_utc"`) and flagged
as a warning, never silently guessed; unparseable values reject the record,
never default to "now". Coordinates: missing stays missing (never defaulted to
`(0,0)`), out-of-range pairs are rejected, not clamped. Severity-&gt;priority:
a documented table; an unrecognized label is left unmapped, never escalated.
All of this is enforced by `validation_service.py`'s structured
`ValidationOutcome` (fatal error codes vs. warning codes, never conflated),
tested exhaustively in `tests/test_normalization.py` (23 tests).

**8. Deduplication and the race-condition fix.** Matching is deterministic
only: `(source_id, external_id)` first, a content fingerprint second, never
similarity/fuzzy matching. Three layers catch a duplicate: an in-batch set, a
cross-batch pre-insert `SELECT`, and -- as the real backstop for a genuinely
concurrent request -- the database's own unique constraint, caught inside a
SQL SAVEPOINT (`db.begin_nested()`) so the failed insert rolls back without
poisoning the rest of the batch's transaction. This was a real design flaw
found and fixed this session (point 12 below), not a feature built correctly
on the first attempt.

**9. Correlation behavior.** `correlation_service.recompute()` is the one
explicit, authorized (`CORRELATION_MANAGE`), audited entry point that produces
candidates -- there is no background job. A pair needs 2+ independent reasons
from `{shared_source_id, shared_asset_reference, compatible_event_type,
temporal_proximity, spatial_proximity}`; `temporal_proximity` alone (the
gatekeeper for even being compared) is never sufficient on its own, directly
satisfying the requirement that repeated reports from the same source never
count as independent corroboration. `match_strength` is a documented weighted
sum, explicitly never presented as a probability of truth. Correlation never
mutates either original `Event` row and never auto-promotes `review_status`.

**10. Source-reliability and evidence-quality separation.** Six genuinely
distinct concepts are kept apart, never collapsed into one score: source
reliability (human-set, reason-required), record validation status (computed,
never human-set), analytical confidence (only set when a real basis exists),
source-reported severity (verbatim, never altered), platform priority
(deterministic mapping from severity), and correlation match-strength (a
triage aid, not evidence). `source_service.set_reliability_weight()` refuses
the call with a `ValueError` if no `reason` is supplied -- enforced
server-side, verified by a dedicated test, not just documented as a UI
convention.

**11. Most important files created or changed.** See `../PROJECT_STATUS.md`
Section 5 for the complete list; the two files changed to fix the real bugs
found this session were `backend/app/connectors/http_connector.py` (except-
clause ordering) and `backend/app/services/ingestion_service.py` (the
SAVEPOINT race-condition fix).

**12. Known defects/blockers found and fixed this session.**
- `http_connector.py`: `except ValueError` was listed before `except
  ConnectorConfigError` (a `ValueError` subclass), so a blocked unsafe
  redirect was mis-reported as a content error instead of an SSRF-blocked
  error. Caught by a test asserting the specific error category; fixed by
  reordering the clauses.
- `ingestion_service.py`: an unprotected `db.add(event); db.flush()` meant a
  genuinely concurrent duplicate's `IntegrityError` would poison the entire
  job's transaction, not just that one record. Fixed with a SAVEPOINT
  (`db.begin_nested()`) scoped to just the insert. Verified with a standalone
  script first, then a `monkeypatch`-forced deterministic test.
- `IngestionJobResponse` schema was initially missing the new
  `trigger_type`/`retry_count`/`correlation_id` fields, caught by a failing
  retry test (`KeyError`), fixed by adding them to the Pydantic response model.

**Known defects/blockers still open:** no live external HTTP source has ever
been connected (the `http_api` connector is tested only against a local mock
server); correlation's distance/time thresholds are reasonable defaults, not
tuned against real operational data (there is none yet); the data-quality
category-code breakdown is capped at 5000 records for performance (the
total/accepted/rejected/duplicate counts themselves are never capped or
approximated); this session's `backend/.venv` has stale absolute paths baked
into its console-script shebangs (an environment/workspace-layout quirk, not
an application defect -- worked around by invoking `./.venv/bin/python3 -m
pytest` directly; see `../PROJECT_STATUS.md` Section 9 for the full note and the
fix for Phase 3). Carried over unchanged from Phase 1: tenant isolation
modeled-not-enforced, Docker Compose unexecuted in this sandbox, refresh
tokens not revocable, frontend `npm audit` findings untriaged.

**13. Commands actually executed in this final verification pass.**
```
cd backend && ./.venv/bin/python3 -m pytest -q --cov=app --cov-report=term-missing
  # 172 passed, 93% line coverage
cd ../frontend && npx tsc -b --force && npx eslint . && npm run build
  # clean, 0 errors / 1 pre-existing warning, build succeeded
git status --short   # reviewed before staging; confirmed .gitignore already
                      # excludes .venv/aegis.db/__pycache__/node_modules/dist/logs
```
The full history of commands run across this phase's development (connector
smoke tests, the SAVEPOINT standalone verification script, the Alembic
upgrade/downgrade/re-upgrade cycle, every earlier `pytest` run during
development) is recorded in `../PROJECT_STATUS.md` Section 7.

**14. Test and build results (this final pass).** Backend: **172 passed**, 0
failed, **93% line coverage**. Frontend: `tsc -b --force` clean; `eslint .` →
0 errors, 1 warning (`AuthContext.tsx`, confirmed via `git status --short` to
be unmodified since the Phase 1 baseline commit `86b9f2c` -- not a regression
from this phase); `npm run build` → succeeded, `dist/` 304.21 kB JS (91.60 kB
gzip) / 14.68 kB CSS (3.49 kB gzip).

**15. Integrations not connected.** No real external HTTP/API source, no
real camera/sensor feed, no message queue or streaming source -- unchanged in
substance from Phase 1. What Phase 2 adds is the *capability*
(`http_connector.py`, SSRF-hardened, tested against a local mock server
started and torn down inside the test process) -- never a live third-party
endpoint actually reached from this sandbox.

**16. Exact startup and test commands for the next session.**
```bash
cd backend
./.venv/bin/python3 -m pip install -r requirements.txt --break-system-packages
  # or rebuild the venv per ../PROJECT_STATUS.md Section 9 if console scripts
  # (`alembic`, `pytest`) fail with ModuleNotFoundError when run by bare name
./.venv/bin/python3 -m alembic upgrade head
./.venv/bin/python3 scripts/seed.py      # safe to re-run
./.venv/bin/python3 -m uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
npm run dev

# Tests:
cd ../backend && ./.venv/bin/python3 -m pytest -q --cov=app --cov-report=term-missing
cd ../frontend && npx tsc -b --force && npx eslint . && npm run build
```
Demo accounts unchanged: `admin` / `analyst` / `investigator` / `viewer`,
password `DevPassword123!`.

**17. Next tasks for Phase 3 (Multisource Intelligence Fusion).** Read
`../PROJECT_STATUS.md` Section 12 in full. In short: Phase 3's probabilistic
fusion is explicitly a different, larger capability than this phase's
deterministic rule-based `EventCorrelation` -- extend/consume it, don't
replace it; rebuild `backend/.venv` cleanly before relying on bare `pytest`/
`alembic` commands; the first real external connector integration should
expect to extend `http_connector.py` for whatever quirks a real source
actually has, since everything here was only ever proven against a mock;
keep the "only claim what was actually run" discipline for every future
phase's own final report.
