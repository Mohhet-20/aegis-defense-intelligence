> **Archived.** This was the repository README during Phases 1-18 and is kept for its historical notes. The current README is [`../../../README.md`](../../../README.md); current status is [`../PROJECT_STATUS.md`](../PROJECT_STATUS.md).

# AEGIS -- AI Defense Intelligence, Threat Assessment and Situational Awareness Platform

A decision-support platform for human analysts, investigators, and administrators.
**This is strictly a defensive, human-in-the-loop system: no autonomous targeting,
weapon control, or engagement logic exists anywhere in this codebase, and none is
planned.**

This repository is being built across 18 phases. **Phase 1 (Phase 1: Enterprise
Foundation), Phase 2 (Phase 2: Advanced Intelligence Data Platform),
Phase 3 (Phase 3: Multisource Intelligence Fusion), Phase 4 (Phase 4:
Enterprise Computer Vision Infrastructure), Phase 5 (Phase 5: Advanced
Object Tracking, Track Lifecycle Management, Motion Analytics, Trajectory
Visualization, and Tracking Evaluation), Phase 6 (Phase 6: Sensor and
Observation Analytics -- multi-sensor ingestion, canonical observation
validation, time-series analytics, statistical anomaly detection, four-signal
sensor health, and cross-source comparison), Phase 7 (Phase 7:
Geospatial and Temporal Intelligence -- bounded spatial/radius/timeline
queries, historical playback, location-quality reporting, spatial
relationship discovery, a 7-section Geospatial Intelligence Workspace with
an interactive Leaflet map, and bounded GeoJSON/CSV export), and Phase 8
(Phase 8: Edge AI, Offline-First Operation, Durable Local Queues, Conflict
Resolution, and Safe Synchronization -- a real device identity/credential/
lifecycle registry, a durable idempotent central sync protocol with an
enforced state machine, a two-tier conflict policy (immutable-type
integrity quarantine vs. mutable-type optimistic-concurrency conflicts,
never last-write-wins), a simulated edge runtime with its own durable
local outbox, and an Edge Operations frontend -- tested in SIMULATION
ONLY, no physical edge hardware available), and Phase 9 (Phase 9:
Enterprise Edge Fleet Management, Device Observability, Health
Monitoring, Capability Inventory, Lifecycle Management, and Operational
Dashboards -- server-computed device presence derived from Phase 8's
existing liveness signal, a standardized health-finding rule engine,
five-state capability discovery, fleet sites/groups reusing Phase 7's
geospatial mixin, configuration baselines with optimistic-concurrency
updates and drift detection, a deduplicated fleet-health infrastructure-
alert queue kept strictly separate from intelligence alerting, an
extended device lifecycle (`maintenance`/`decommissioned`) with
confirmation previews, and a live fleet analytics snapshot -- also
tested in SIMULATION ONLY) are complete.**
Phase 10 (Phase 10: Explainable AI, Model Evaluation, Uncertainty Analysis and Analyst Decision Support) is also complete: model-output normalization, classification evaluation, faithful explanations, advisory assessment scoring and human review -- see `docs/architecture/EXPLAINABLE_ANALYTICS_ARCHITECTURE.md`. Before touching any code, read

Phase 11 (Phase 11: Investigation Management, Evidence Provenance, Timelines and Review Workflows) is also complete: lifecycle with history, evidence registry with integrity verification and provenance, computed UTC timeline, versioned notes, scoped search and reproducible exports -- see `docs/architecture/INVESTIGATION_WORKSPACE.md`.

Phase 13 (Phase 13: Scenario Simulation, What-If Analysis, Synthetic Data and Sensitivity Analysis) is also complete as a bounded slice: three registered simulators on a deterministic synthetic generator, versioned scenarios, reproducible runs, comparison and one-parameter-at-a-time sensitivity. All output is labelled simulated and kept out of operational data -- see `docs/architecture/SCENARIO_SIMULATION.md`.

Phase 16 (Advanced analytics, executive dashboards, reporting) is complete as a tested slice -- see `docs/analytics/ANALYTICS_ARCHITECTURE.md`, `docs/analytics/METRIC_DEFINITIONS.md` and `docs/api/REPORTING_API.md`.

Phase 15 (Enterprise MLOps, experiment tracking, monitoring and observability) is complete as a tested slice -- see `docs/ml/MLOPS_ARCHITECTURE.md`, `docs/ml/MLOPS_MONITORING.md` and `docs/operations/OBSERVABILITY.md`.

Phase 14 (Security, Authorization, Tenant Isolation, Audit Governance and Data Lifecycle) is complete as a tested slice -- see `docs/security/` and `docs/security/KNOWN_RISKS.md` for what is and is not covered.

Phase 12 (Phase 12: Intelligence Copilot, Retrieval and Citations) is also complete as a keyword-retrieval slice: a derived search index with live authorization, extractive/deterministic cited answers, structured citations and conversations. No language-model or embedding provider is configured by default and semantic search is not implemented -- see `docs/architecture/RETRIEVAL_COPILOT.md` and `docs/security/COPILOT_PRIVACY.md`.
[`docs/implementation/PROJECT_STATUS.md`](../PROJECT_STATUS.md) --
it is the permanent, honestly-maintained handoff record of what actually exists,
what was actually tested, and what is deliberately deferred.

## What's here

- `backend/` -- FastAPI + SQLAlchemy 2.0 + Alembic, SQLite by default,
  Postgres-capable. REST API under `/api/v1`. Phase 2 adds a connector
  architecture (HTTP/JSON/CSV/synthetic, SSRF-hardened), normalization +
  validation engines, raw-record provenance, rule-based event correlation,
  data-quality/source-reliability reporting, and controlled CSV/JSON export.
  Phase 3 adds an evidence reference layer, directional evidence
  relationships with a confirm/reject/uncertain/reverse workflow, conflict
  detection scoped to existing correlations, a bounded evidence graph, and a
  versioned, evidence-cited Assessment workflow -- see
  `docs/architecture/INTELLIGENCE_FUSION_ARCHITECTURE.md`.
- `frontend/` -- React + TypeScript + Vite + Tailwind SPA, deep navy/charcoal
  enterprise UI, talking to the real backend (no mocked data). Phase 2 adds a
  data-operations workspace: source management, job detail/retry, data-quality
  and correlation review pages, provenance on the event detail page. Phase 3
  adds a fusion workspace: an overview page, an evidence library, a
  relationship review queue, a conflict review center, a bounded evidence
  graph explorer (SVG + accessible table), and an assessment workspace with
  version history. Phase 4 adds secure media ingestion (signature-sniffed,
  content-addressed, never trusting a client's filename/content-type), a CV
  model registry (extends Phase 1's `ModelRecord`, closed adapter
  allow-list), synchronous image/bounded-video inference jobs, real NMS-based
  detection postprocessing with a class-label allow-list, a never-auto-promote
  analyst review workflow into Phase 3's `Evidence`, and deterministic
  synthetic-dataset model evaluation -- see
  `docs/architecture/COMPUTER_VISION_ARCHITECTURE.md`. Phase 5 adds temporary,
  sequence-scoped multi-object tracking directly over Phase 4's
  `DetectionResult` rows: a reusable tracker interface with one deterministic
  IoU + Hungarian-assignment baseline tracker, explicit track lifecycle states,
  image-space-only (pixel) motion analytics, non-destructive analyst
  annotations, and custom-defined tracking evaluation against a deterministic
  synthetic fixture (never HOTA/IDF1/MOTA) -- see
  `docs/architecture/OBJECT_TRACKING_ARCHITECTURE.md`. Phase 6 adds a
  canonical observation-validation layer (`app/sensors/quality.py` --
  timestamp normalization, unit conversion, range/duplicate/stale checks)
  sitting in front of Phase 1's `Sensor`/`Observation` tables, three
  deterministic ingestion adapters (synthetic/CSV/JSON) behind a closed
  registry, bounded/downsampled time-series queries with honest
  truncation disclosure, four statistical anomaly-detection methods (never a
  black-box ML model), a four-signal sensor-health model that is never
  collapsed into one score, and read-only cross-source observation
  comparison -- see `docs/architecture/SENSOR_DATA_ARCHITECTURE.md`. Phase 7
  adds a geospatial intelligence layer: a shared `GeoLocationMixin` extension
  (coordinate reference system, provenance, uncertainty, altitude) across
  `Event`/`Sensor`/`Observation`/`Asset`, a pure-logic `app/geo/` package
  (haversine distance, coordinate validation/quality classification),
  bounded viewport/radius spatial queries with antimeridian handling, bounded
  timeline queries powering real (never-interpolated) historical playback,
  location-quality reporting, rule-based spatial-relationship candidate
  generation reusing Phase 3's `EvidenceRelationship`/`Evidence` models
  (never duplicating Phase 3's conflict-detection logic), bounded
  spatial-grid/temporal-gap analytics, and CSV-injection-safe bounded
  GeoJSON/CSV export -- see
  `docs/architecture/GEOSPATIAL_INTELLIGENCE_ARCHITECTURE.md`. Phase 8
  adds a real edge device registry and credential lifecycle (`Device`
  extended with 16 columns, bcrypt-hashed one-time-displayed API keys,
  `pending`/`active`/`suspended`/`revoked` states), a durable idempotent
  sync protocol (`SyncRecord`'s enforced state machine, a DB-unique
  idempotency constraint, four distinct timestamps, central-receipt-order
  authority -- never a device's own clock), a two-tier conflict policy
  (immutable-type integrity quarantine vs. the one mutable type's
  `base_revision`/`revision` optimistic concurrency, surfaced as a
  separate, human-resolved `SyncConflict` model -- deliberately distinct
  from Phase 3's `Conflict`), a simulated edge runtime (`app/edge/` --
  a genuinely separate local SQLite outbox, real HTTP sync traffic via
  `httpx`, a closed synthetic-inference-adapter registry), and crash-
  recovery sweeps on both sides, manually/externally triggered since no
  background scheduler exists anywhere in this project -- see
  `docs/architecture/EDGE_ARCHITECTURE.md`. **Tested in SIMULATION ONLY --
  no physical edge hardware is available in this environment.** Phase 9
  adds enterprise fleet management directly on top of Phase 8's
  `Device`/`SyncRecord`/`DeviceHealthReport` foundation (extended, never
  duplicated): server-computed presence (`presence_state`, kept
  genuinely separate from Phase 8's device-self-reported
  `connectivity_state`) derived purely from `Device.last_seen_at`, a
  standardized health-finding rule engine (`presence_offline`/
  `presence_stale`/`disk_usage_high`/`battery_low`/`sync_queue_backlog`)
  with explicit missing-data/stale-vs-fresh/device-vs-server-computed
  discipline, five-state-per-capability discovery
  (`supported`/`installed`/`available_and_ready` device-reported,
  `healthy`/`last_verified_at` server-computed, `healthy=None` meaning
  never verified rather than unhealthy), fleet sites/groups reusing
  Phase 7's `GeoLocationMixin` rather than new coordinate columns,
  configuration baselines with optimistic-concurrency updates
  (`expected_revision`, 409 on mismatch) and key-by-key drift detection
  (a missing baseline is never reported as "no drift"), a dedicated
  `InfrastructureAlert` queue with service-layer deduplication by a
  stable `dedup_key` -- deliberately separate from intelligence
  `Event`/`ObservationAnomaly`/`RiskAssessment` alerting, with no real
  external notification sent -- and an extended administrative
  lifecycle adding `maintenance` (a temporary, reversible,
  non-security pause) and `decommissioned` (a permanent,
  non-security end-of-life, never deleting historical sync/health/audit
  rows) alongside a read-only confirmation-preview endpoint for every
  consequential transition -- see
  `docs/architecture/FLEET_MANAGEMENT.md`. **Tested in SIMULATION ONLY
  -- no physical edge hardware is available in this environment; the
  heartbeat rate limiter is a documented single-process, best-effort
  limiter, not multi-process-safe -- see
  `docs/security/DEVICE_LIFECYCLE_SECURITY.md`.**
- `frontend/` -- Phase 4 adds an 8-workflow CV Analyst Workspace: overview,
  media library, image detection (with a responsive bounding-box SVG
  overlay), bounded video analysis, model registry, inference job
  monitor/detail, model evaluation, and CV-to-evidence links. Phase 5 adds a
  7-page Tracking Analyst Workspace: overview, a video+track submission
  workspace (live multi-track SVG overlay on real `<video>` playback), job
  monitor/detail, track detail (lifecycle timeline, trajectory plot,
  observation history, annotation workflow), track comparison, and a tracking
  evaluation workspace. Phase 6 adds a Sensor Intelligence Workspace: a
  rewritten Sensor Registry (filters, lifecycle badges, extended create
  form), a Sensor Detail page (hand-rolled SVG time-series chart -- no
  charting library in this project -- colored by validation status, a
  four-signal health card, lifecycle action buttons, descriptive statistics,
  status-history audit trail), a Sensor Ingestion Monitor, an Anomaly Review
  Center, and a Cross-Source Comparison page -- all live-verified in a real
  browser session against the real backend and real seeded data, zero
  console errors. Phase 7 adds a 7-section Geospatial Intelligence
  Workspace: an Overview, an Interactive Map Explorer (Leaflet, marker
  clustering, a configurable tile source with no hardcoded API key -- see
  `docs/operations/MAP_PROVIDER_CONFIGURATION.md`), a Timeline Explorer with
  real historical playback, a Location Quality Center, a Spatial
  Relationship Explorer (reusing the existing relationship review
  endpoint), a Geographic Analytics Dashboard (spatial grid + temporal
  gaps), and an Export Center (GeoJSON/CSV) -- all live-verified in a real
  browser session, including two real interaction tests (confirming a
  spatial-relationship candidate; downloading a real GeoJSON export).
  Phase 8 adds an Edge Operations surface: an Edge Device List/Detail
  (Overview/Sync Activity/Health History/Audit Trail tabs, a one-time-
  display API key field), a Sync Queue page, and a Conflict Review
  workspace (side-by-side `local_version`/`central_version` JSON
  comparison) -- live-verified against real running servers, including a
  genuine cross-device conflict resolved end-to-end through the real UI
  and a genuine quarantined integrity-failure record. Phase 9 adds the
  Fleet Operations Center -- `pages/fleet/FleetOverviewPage.tsx`,
  `FleetSitesPage.tsx`, `FleetAlertCenterPage.tsx` (routed at
  `/fleet/overview`, `/fleet/sites`, `/fleet/alerts`), plus
  capability/configuration/lifecycle/site-assignment extensions to
  `EdgeDeviceListPage.tsx`/`EdgeDeviceDetailPage.tsx` -- built
  concurrently by a separate effort in this same phase and
  independently verified via a clean `tsc`/`build`/`lint` pass; this
  documentation pass observed these pages exist and are routed but did
  not itself build, modify, or click-through-verify them in a browser
  (that work stayed entirely in `backend/`/`docs/` -- see
  `docs/testing/FLEET_TESTING.md` Section 4).
- `docs/` -- architecture decisions, module catalog, per-domain "future extension"
  contracts (geospatial, edge sync, AI analytics -- still `PLANNED`; the
  computer-vision contract doc is now marked superseded by the real Phase 4
  implementation, see `docs/architecture/COMPUTER_VISION_CONTRACTS.md`; the
  multisensor contract doc's Phase 6 section is now superseded by the real
  Phase 6 implementation, see `docs/architecture/SENSOR_DATA_ARCHITECTURE.md`),
  security baseline, API reference, data-platform docs (connector
  architecture, canonical schema, provenance, deduplication, correlation,
  source reliability), intelligence fusion docs (evidence/relationship model,
  temporal/spatial correlation, conflict detection, confidence separation,
  evidence graph, analyst review and assessment lifecycle workflows, fusion
  API, fusion test strategy), computer vision docs (architecture, media/
  detection schemas, model registry/adapters, inference pipeline, video frame
  analysis, model evaluation, media upload security, CV operations, CV API,
  CV test strategy), object tracking docs (architecture, tracker adapters,
  detection-to-track association, track lifecycle, image-space motion
  analytics, tracking evaluation, tracking result schema, tracking API,
  tracking data governance, tracking operations, tracking test strategy),
  sensor/observation analytics docs (architecture, canonical observation
  schema, sensor registry, measurement units and quality, time-series
  analytics, anomaly detection, sensor health, cross-source comparison,
  sensor API, sensor ingestion operations, sensor data governance, sensor
  analytics test strategy), geospatial intelligence docs (architecture,
  location schema/coordinate systems, location provenance/uncertainty,
  spatial query design, temporal exploration, spatial/temporal analytics,
  location quality, spatial relationships, geospatial API, geographic data
  governance, map provider configuration, geospatial test strategy), edge
  AI / offline-sync docs (architecture, sync protocol, offline operations,
  conflict resolution, edge device security, edge troubleshooting, local
  storage and retention, edge inference, edge testing), enterprise
  fleet management docs (fleet management architecture, device health
  model, fleet operations, infrastructure alerts, device lifecycle
  security, fleet testing), and the project status handoff doc above.

## Quick start (any OS)

You need Python 3.11+ and Node 18+. Commands below are POSIX shell; Windows
equivalents follow in the next section.

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # defaults work as-is for local dev
alembic upgrade head
python scripts/seed.py          # creates admin/analyst/viewer demo accounts
uvicorn app.main:app --reload --port 8000

# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173, proxies /api to :8000
```

Sign in with `admin` / `analyst` / `investigator` / `viewer`, password
`DevPassword123!` (seeded, synthetic demo accounts only -- never use these in a
real deployment).

## Windows-specific notes

PowerShell commands differ from Bash in a few places that matter here:

- Activating the virtualenv: `.venv\Scripts\Activate.ps1` (PowerShell) or
  `.venv\Scripts\activate.bat` (cmd.exe) -- **not** `source .venv/bin/activate`.
- Copying the env file: `Copy-Item .env.example .env` (PowerShell) instead of `cp`.
- Setting an environment variable for one command (used in troubleshooting below):
  PowerShell is `$env:DATABASE_URL = "..."` then run the command on the next line
  -- **not** `DATABASE_URL=... command` (that Bash-only inline-env-var syntax is
  silently wrong in PowerShell, not an error, so double-check it took effect with
  `echo $env:DATABASE_URL`).
- Background processes: PowerShell doesn't have `nohup`/`&` the same way Bash
  does. Use `Start-Process uvicorn -ArgumentList "app.main:app","--port","8000"`
  or just run it in its own terminal tab/window.
- Path separators in `.env`/`DATABASE_URL` for a file-based SQLite path should
  still use forward slashes (`sqlite:///./aegis.db`) -- SQLAlchemy's SQLite URL
  format doesn't use OS-native backslashes even on Windows.

## Running the automated tests

```bash
cd backend
pytest                              # 71 tests as of Phase 1, 172 as of Phase 2, 227 as of Phase 3, 291 as of Phase 4, 368 as of Phase 5, 507 as of Phase 6, 620 as of Phase 7, 718 as of Phase 8, 784 as of Phase 9, 1363 as of Phase 17 (CI: .github/workflows/ci.yml; see docs/testing/INTEGRATION_TESTING.md)
pytest --cov=app --cov-report=term-missing   # with coverage (95% Phase 1, 93% Phase 2, 90% Phase 3, 91% Phase 4, 92% Phase 5, 92% Phase 6, 93% Phase 7, 93% Phase 8, 93% Phase 9), 94% Phase 17

cd ../frontend
npx tsc -b                          # type-check (npx tsc --noEmit also works)
npx eslint .                        # lint (src/ has 0 errors as of Phase 8; 2 warnings --
                                     # 1 pre-existing AuthContext.tsx warning carried over, 1
                                     # intentional react-hooks/exhaustive-deps in SensorDetailPage.tsx)
npm run build                       # production build -> frontend/dist/
```

**Phase 8 note: the simulated edge runtime (`app/edge/`) has only ever
been exercised in simulation.** No physical edge hardware is available in
this development environment -- `SimulatedEdgeNode` makes real HTTP calls
against the real backend (a live server or an in-process ASGI transport in
tests), but nothing here has run on, or been validated against, actual
device hardware. See `docs/architecture/EDGE_ARCHITECTURE.md` Section 18.

**Phase 9 note: the heartbeat rate limiter
(`app/services/fleet_presence_service.py`) is single-process and
best-effort, not multi-process-safe.** This project has no shared
cache/broker; a real distributed limiter would be needed before this
backend is ever deployed with multiple worker processes or replicas.
See `docs/security/DEVICE_LIFECYCLE_SECURITY.md` Section 6.

**Phase 7 note: the Interactive Map Explorer needs a map tile provider
configured before it renders tile imagery.** Copy
`frontend/.env.example` to `frontend/.env` and set `VITE_MAP_TILE_URL`
(no default is bundled -- see `docs/operations/MAP_PROVIDER_CONFIGURATION.md`
for why and for provider options). Without it, the page shows an
informative fallback card and an accessible list view instead of a
blank/broken map -- markers, clustering, and spatial queries all still
work.

Phase 2's connector/SSRF tests spin up a local `http.server.HTTPServer` bound
to `127.0.0.1` as a mock HTTP source -- no real external network access is
required to run the suite, and none should be assumed available in CI.

**Phase 4 note: `opencv-python-headless` must be the pinned `4.14.0.94` (the
4.x line), not the default-installed `5.0.0.x`.** Version 5.0.0 removed
`cv2.HOGDescriptor`/`cv2.CascadeClassifier` from its Python bindings entirely,
which breaks the real CV adapter and the `/health/ready` model-runtime check.
`pip install -r requirements.txt` installs the correct pin; if you've
previously `pip install`ed a bare `opencv-python-headless` into this venv, run
`pip install -r requirements.txt` again to force it back to the pin (verify
with `python -c "import cv2; print(cv2.__version__, hasattr(cv2,'HOGDescriptor'))"`
-- should print `4.14.0 True`).

## Running with Docker

`docker-compose.yml` builds the backend, frontend, and a Postgres service.
**Important, read before relying on this:** the Dockerfiles and compose file were
written and reviewed in this phase, but could not be executed in the sandbox
this was built in (no working Docker daemon there -- see
`docs/implementation/PROJECT_STATUS.md` Section 9). The Postgres connectivity
path they rely on *was* verified, just against a directly-installed Postgres, not
through Docker. Treat `docker compose up --build` as the next thing to verify in
an environment where Docker actually runs, not as already-proven.

```bash
docker compose up --build
# backend:  http://localhost:8000
# frontend: http://localhost:8080
```

## Troubleshooting

**`ValueError: password cannot be longer than 72 bytes` when seeding.** This was a
real bug hit during development (a `passlib`/`bcrypt` version incompatibility).
It's already fixed -- `app/core/security.py` calls `bcrypt` directly, and
`passlib` isn't a dependency anymore. If you see this, you likely have a stale
`passlib` install in your environment; `pip uninstall passlib` and reinstall from
`requirements.txt`.

**Account "temporarily locked" after a few failed logins.** Intentional (Section
9 of the original spec) -- 5 failed attempts locks the account for 15 minutes
(`MAX_FAILED_LOGIN_ATTEMPTS` / `ACCOUNT_LOCKOUT_MINUTES` in `app/core/config.py`).
Wait it out, or for local dev, delete `backend/aegis.db` and re-seed.

**Backend refuses to start with `Refusing to start: ENVIRONMENT=production but
SECRET_KEY is still the development placeholder`.** This is a deliberate safety
check (`_check_production_safety()` in `app/main.py`) -- set a real `SECRET_KEY`
environment variable before setting `ENVIRONMENT=production`. It is not a bug.

**Frontend shows "Database unreachable" in the sidebar.** The frontend polls
`GET /api/v1/health/ready` on load. Make sure the backend is actually running on
port 8000 and that `alembic upgrade head` has been run at least once (a missing
schema also shows as "unreachable").

**CORS errors in the browser console.** `CORS_ALLOWED_ORIGINS` in `backend/.env`
must include whatever origin the frontend is actually served from (default
`http://localhost:5173` for `npm run dev`). Multiple origins are comma-separated.

**Tests pass locally but take noticeably longer than the ~6 seconds documented in
`../PROJECT_STATUS.md`.** The test suite lowers bcrypt's work factor for speed (see
`backend/tests/conftest.py`) -- if you've modified that file, a full 12-round
bcrypt hash per seeded user will make the suite take minutes rather than seconds.
This is a test-only setting; production hashing is untouched.

**`POST /sources/{id}/run` or `check-connectivity` fails with "resolves to a
disallowed address" against a source I expected to work.** This is the SSRF
guard in `app/connectors/url_safety.py` working as designed, not a bug --
loopback/private/link-local/reserved/multicast destinations are blocked
unconditionally for `https` sources, and `http` is only ever permitted when
the source's config explicitly sets `allow_local_dev=True` **and** the
resolved host is loopback. See `docs/architecture/CONNECTOR_ARCHITECTURE.md`.

## Deployment notes

Not yet in scope for Phase 1. `docs/security/SECURITY_BASELINE.md` lists exactly
what security controls exist today and what's explicitly deferred (TLS
termination, secret management beyond environment variables, rate-limit tuning
for a real deployment, etc.) -- read it before deploying this anywhere real.


## Deploying (Phase 18)
See `docs/operations/DEPLOYMENT_GUIDE.md` (native and Docker Compose), `ADMINISTRATOR_GUIDE.md`, `BACKUP_AND_RESTORE.md`, `RUNBOOKS.md` and `RELEASE_VERIFICATION.md` for what was and was not verified. Create the first administrator with `backend/scripts/bootstrap_admin.py`; run `backend/scripts/smoke_test.py` against any new deployment.
