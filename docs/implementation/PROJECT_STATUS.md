# AEGIS -- Project Status

**Last updated:** 2026-10-19, release candidate `1.0.0-rc.3` (committed on `release/final-stabilization`,
not pushed). **Read this section first.** Everything below "Historical record" is the per-phase record,
kept unchanged; where they disagree, this section wins. Nothing here is claimed unless it was run and
observed; evidence: `docs/operations/RELEASE_VERIFICATION.md`.

## Current state

**Status: release candidate, verified end to end on Windows 11 with SQLite and PostgreSQL 16; MIT
licensed. Not yet executed: the GitHub Actions workflow and the Docker images (no remote, no Docker
in the verification environment).** Migration head `c16r3p0rt01`.

| Evidence (final code) | Result |
|---|---|
| Backend suite, SQLite | 1426 passed, 1 skipped (SQLite-only skip), 0 failed |
| Backend suite, PostgreSQL 16.10 (non-UTC session zone) | 1415 passed, 0 failed on rc.2 (PGTZ=Asia/Kolkata); rc.3: the 87 demo, auth, user and sweep tests re-run there, 87 passed |
| Frontend | lint 0 errors / 0 warnings; 59 Vitest tests; type-check + build; `npm audit` 0 vulnerabilities |
| Browser | 76/76 routes for each of the 4 roles and at 390 px on the production build under the CSP; session journey 11/11 |
| Real detector | SSD-MobileNet v1 COCO: mAP@0.5 0.461 on 200 COCO photos (HOG baseline 0.003) |
| Security scans | pip-audit, bandit, `npm audit`, detect-secrets: all clean |

### Subsystem status

Legend: **Verified** -- automated tests plus end-to-end exercise here. **Partially verified** -- a
relevant scenario or environment is untested. **Simulated** -- works over synthetic or simulated inputs
by design. **Unverified** -- present, never executed. **Not implemented.**

| Subsystem | Status | Evidence / limits |
|---|---|---|
| Auth, sessions, RBAC (4 roles) | Verified | HttpOnly refresh cookie + in-memory access token (browser-verified); sweeps over every operation on SQLite and PostgreSQL; key rotation grace period. No MFA/SSO |
| Organization (tenant) isolation | Verified | cross-tenant sweeps and integrity tests on both engines; enforced per query |
| Ingestion & provenance | Verified | workflow B, smoke, demo; HTTP connector tested against a local mock server |
| Data quality & correlation | Verified | module tests on both engines |
| Sensors, observations, anomalies | Simulated (synthetic data) | sensor suites; no hardware |
| Fusion: evidence, relationships, conflicts, assessments | Verified | workflow C, demo |
| Investigations, timeline, notes, export | Verified | workflow E, demo; audit log not tamper-proof |
| Media storage & private access | Verified | smoke on both engines, backup/restore, orphan sweeper |
| CV inference | **Verified -- real pretrained detector** | SSD-MobileNet v1 COCO (person, vehicle), SHA-256-verified weights, real inference on real photos; HOG baseline; mock kept for pipeline tests. CPU only; not validated on operational imagery |
| Model evaluation | **Verified on real images** + synthetic pipeline check | COCO val2017 sample (AP@0.5 per class) through production post-processing; API, MLOps and UI |
| Tracking | Simulated (synthetic video) | tracking suites, demo step 6 |
| Geospatial | Verified | plain-Leaflet map browser-tested with tiles under the CSP; truncation now disclosed |
| Edge sync & fleet | Simulated | simulated devices only |
| Explainability & decision support | Verified | advisory only by design |
| Retrieval & copilot | Partially verified | BM25 retrieval verified; external LLM provider off by default, tested with mocks |
| Scenarios | Simulated by design | labelled SIMULATED |
| MLOps registry, experiments, monitoring | Verified | real-image detection experiments now supported |
| Analytics dashboards & reports | Verified | UTC-correct on SQLite and on non-UTC PostgreSQL servers |
| Security controls | Verified | CSP, cookie sessions, production start-up refusals, size limits, audit |
| Observability | Partially verified | JSON logs (redaction checked), health; metrics per process |
| Backup / restore | Verified | SQLite and PostgreSQL round trips with application read-back |
| PostgreSQL deployment | Verified (single host) | full suite, migrations incl. downgrade to base, production smoke, restart, backup/restore |
| Frontend tests | Verified (component/unit level) | Vitest: navigation, guards, badges, error boundary, API client and session handling, CSP rendering, map wrapper; pages also covered by browser walks |
| Public demo (one container, `DEMO_MODE`) | Verified outside Docker | demo server run with the image's exact settings: reset/seed/walkthrough, real-detector showcase, one-click sign-in, 76/76 routes for two roles, CSP and framing headers; demo-mode tests. Image build itself not run here (CI `demo-image` job) |
| Docker / Compose | Unverified | files reviewed; CSP rendering unit-tested; images never built |
| CI (GitHub Actions) | Unverified (authored, not executed) | YAML and every shell block validated locally |
| Background job queue, PDF/scheduled reports, MFA, HA, GPU | Not implemented | -- |

### Next actions
1. **Owner:** push to a private GitHub repository and get every CI job green, especially `containers`
   (never built) and the Python 3.12/3.13 legs (`docs/operations/GITHUB_PUBLICATION.md`).
2. Optional hardening: MFA, tamper-evident audit (hash chain), shared rate-limit store for multi-process
   deployments, background job queue for long inference.
3. Optional ML: a newer detector (e.g. a YOLO-class ONNX model) through the same adapter interface,
   evaluated on the same COCO sample and on domain data if any becomes available.

---

## Historical record (phases 1-18, written during the build)

The original header read: "Last updated: Phase 18 of 18 ... nothing below is claimed unless it was actually run and observed in this session." Each section below describes its own phase's session.

## Phase 13 update (Phase 13: Scenario Simulation, What-If, Synthetic Data, Sensitivity)

**Phase 13: COMPLETE (bounded, reproducible vertical slice).** Scenario definitions (draft/ready/archived, templates, immutable versions
with lineage) separate from runs (immutable config snapshot, seed, versions, dataset reference + hash, result SHA-256, measured runtime,
safe errors, idempotency, retry). A pure-Python engine (`app/simulation/`) with a deterministic synthetic time-series generator (missing/
delayed/noisy data, outliers, duplicates, out-of-order, skew, incomplete metadata, per-source bias/noise), **three simulators**
(`threshold_detection`, `source_availability`, `duplicate_out_of_order`), what-if comparison with attribution rules, and
one-parameter-at-a-time sensitivity sweeps (no confidence intervals are computed). Everything is labelled SIMULATED in storage, API,
exports, search index and UI, and is kept out of operational tables. 3 new tables (migration `980f1f55cbaa`, tested up/down/up,
`alembic check` clean), 3 new permissions, 21 route handlers, `/scenarios` workspace (builder, overview, runs + run details,
compare, sensitivity), and an opt-in `scenario` retrieval type excluded from default search/copilot. **Not built:** simulators for
model-evaluation comparison and assessment-parameter changes, cancellation/background execution, OS-level resource isolation.
**Tests actually run: 1052 passed (919 prior + 133 new: 60 engine, 73 API)**; frontend `tsc`, `eslint` (0 errors, the same 2 pre-existing
warnings) and `vite build` pass; the frontend was not exercised in a browser.
Details: `docs/architecture/SCENARIO_SIMULATION.md`, `docs/api/SCENARIO_API.md`, `docs/security/SCENARIO_DATA_SEPARATION.md`,
`docs/implementation/history/PHASE_13_FINAL_REPORT.md`. The rest of this file is the Phase 12/11/10/9 record, otherwise unchanged.

## Phase 12 update (Phase 12: Intelligence Copilot, Retrieval, Citations)

**Phase 12: COMPLETE (keyword-retrieval vertical slice).** A derived, refreshable retrieval index (`retrieval_documents`,
`retrieval_chunks`, `retrieval_index_runs`) over investigations, notes, events, observations, assessments and reviews, evidence,
data sources and media metadata; idempotent explicit indexing with versioning and invalidation; **BM25 keyword search** with
filters and pagination whose results are re-authorized against the live record on every query (revocation takes effect without
re-indexing); an evidence-grounded copilot whose default mode is **extractive and deterministic** (cited verbatim excerpts, investigation
summary, chronology, side-by-side comparison with unresolved conflicts, related records, assembled report draft); structured citations
that are re-verified against current data and permissions; per-user conversations with hard delete and retention purge; a provider layer
(generation interface, optional Anthropic Messages adapter, strict output schema) that is **disabled and unconfigured by default**; a
synthetic-fixture retrieval evaluation (P@K, R@K, MRR, nDCG). 5 new tables (one migration `96f00457bcd4`, tested up/down/up, `alembic check`
clean), 3 new permissions, 13 new route handlers, `/copilot` page and an investigation "Copilot" tab. **Not built:** semantic/embedding search,
a configured language-model provider (the adapter is tested only with mocks), automatic/background indexing, OCR. **Tests actually run:
919 passed (873 prior + 46 new)**; frontend `tsc`, `eslint` (0 errors, same 2 pre-existing warnings) and `build` pass; frontend not browser-tested.
Details: `docs/architecture/RETRIEVAL_COPILOT.md`, `docs/security/COPILOT_PRIVACY.md`, `docs/api/RETRIEVAL_COPILOT_API.md`,
`docs/implementation/history/PHASE_12_FINAL_REPORT.md`. The rest of this file is the Phase 11/10/9 record, otherwise unchanged.

## Phase 11 update (Phase 11: Investigations, Evidence Provenance, Timelines, Review)

**Phase 11: COMPLETE (vertical slice).** Extends `Investigation` and `Evidence` (no parallel models): explicit lifecycle
(`draft/open/active/pending_review/closed/archived`) with closure reasons and append-only status history; restricted
investigations and members/reviewers; record links; evidence registry with `aegis://` references, SHA-256 recording,
on-demand integrity verification (append-only results; integrity is not authenticity), derived provenance chains and
append-only supersession; a computed UTC timeline that keeps event/capture/ingestion/processing/review times distinct and
shows unknown times explicitly; versioned notes with optimistic concurrency and full revision history; investigation-scoped
search and relationship view (origin shown, nothing auto-promoted); reproducible JSON/ZIP export with a SHA-256 manifest
and omitted-artifacts list, explicitly not independently authenticated. 6 new tables + extended columns (one migration,
`6e2842cef39a`, tested up/down/up), 1 new permission (`investigation:export`), 28 new route handlers, rewritten
Investigations dashboard and a 5-tab detail workspace. **Tests actually run: 873 passed (836 prior + 37 new), 0 failed**
on a sandbox whose library versions differ from the pins; frontend `tsc`, `eslint` (0 errors, 2 pre-existing warnings) and
`build` pass. Frontend not browser-tested. Details: `docs/architecture/INVESTIGATION_WORKSPACE.md`,
`docs/api/INVESTIGATION_WORKSPACE_API.md`, `docs/implementation/history/PHASE_11_FINAL_REPORT.md`. The audit log is an application
log, not a certified chain of custody. The rest of this file is the Phase 10/9 record, otherwise unchanged.

## Phase 10 update (Phase 10: Explainable AI, Evaluation, Uncertainty, Decision Support)

**Phase 10: COMPLETE.** Adds a shared model-output schema over detections and risk assessments;
classification/probability evaluation with explicit undefined-metric handling; an extensible,
faithful explanation interface (unsupported methods are shown, never faked); transparent advisory
review-priority scoring with model confidence / evidence quality / source reliability / uncertainty /
priority kept distinct; and an append-only human review workflow with audit events. 3 new tables (one
migration, `75b9cd8a733e`), 3 new permissions, 11 routes, 4 pages + an advisory panel in the assessment
page. **Tests actually run: 836 passed (784 prior + 52 new), 0 failed**, on a sandbox environment whose
library versions differ from the pins (see `history/PHASE_10_FINAL_REPORT.md` section 5); frontend `tsc`, `eslint`
(0 errors) and `build` pass. Frontend not browser-tested. Details: `docs/architecture/
EXPLAINABLE_ANALYTICS_ARCHITECTURE.md`, `docs/implementation/history/PHASE_10_FINAL_REPORT.md`. The rest of this
file below is the Phase 9 record and is otherwise unchanged.

## 1. Project identity and scope

AEGIS -- AI Defense Intelligence, Threat Assessment and Situational Awareness
Platform. A **decision-support** platform for human analysts/investigators.
**Strictly defensive scope**: no autonomous targeting, weapon control, or
engagement logic exists anywhere in this codebase, and none is planned in any
future phase. This statement appears in the backend's own OpenAPI description
(`app/main.py`) and should be repeated in every future phase's work.

18-phase roadmap: see `docs/implementation/MASTER_ROADMAP.md`. Phase 1
delivered **Phase 1: Enterprise Foundation**. Phase 2 delivered **Phase 2:
Advanced Intelligence Data Platform**. Phase 3 delivered **Phase 3:
Multisource Intelligence Fusion**. Phase 4 delivered **Phase 4: Enterprise
Computer Vision Infrastructure**. Phase 5 delivered **Phase 5: Advanced
Object Tracking, Track Lifecycle Management, Motion Analytics, Trajectory
Visualization, and Tracking Evaluation**. Phase 6 delivered **Phase 6:
Sensor and Observation Analytics**. Phase 7 delivered **Phase 7:
Geospatial and Temporal Intelligence**. Phase 8 delivered **Phase 8: Edge AI,
Offline-First Operation, Durable Local Queues, Conflict Resolution, and Safe
Synchronization**. This phase (Phase 9) delivers **Phase 9: Enterprise
Edge Fleet Management, Device Observability, Health Monitoring, Capability
Inventory, Lifecycle Management, and Operational Dashboards** -- server-
computed device presence derived purely from Phase 8's existing
`Device.last_seen_at` (kept genuinely separate from Phase 8's own
device-self-reported `connectivity_state`); a standardized health-finding
rule engine with three binding measurement-quality rules (missing data
stays missing, stale vs. fresh distinguished, device-reported vs.
server-computed distinguished); a `DeviceCapability` model tracking five
genuinely independent per-(device, capability) states; `FleetSite`
deployment groups reusing Phase 7's `GeoLocationMixin`; `DeviceConfigBaseline`
with optimistic-concurrency config updates and key-by-key drift detection;
a dedicated, deduplicated `InfrastructureAlert` queue kept strictly
separate from intelligence alerting, with no real external notification
sent; an extended administrative lifecycle adding `maintenance`/
`decommissioned` alongside a read-only confirmation-preview endpoint for
every consequential transition; and a live, point-in-time fleet-analytics
snapshot. **Explicitly NOT this phase's scope, and not built:** a
distributed/multi-process-safe rate limiter, any retention/purge job for
the four new tables, a real external notification channel, an evaluator
for the reserved `capability_unhealthy` alert type, any stored historical
trend series, and a live browser click-through/Playwright verification
of the frontend -- all deliberately absent, by design or by this
phase's own documented limitation, not by oversight. (The frontend's
Fleet Operations Center pages and device-detail capability/config/
lifecycle extensions were built this phase and independently verified
via a clean `tsc`/`build`/`lint` pass -- see Section 3.) **Tested in
SIMULATION ONLY -- no physical
edge hardware is available in this environment**, inherited directly from
Phase 8's own standing limitation.

## 2. Architecture actually implemented

Still a modular monolith -- one FastAPI process, one database, one React SPA,
plus a private content-addressed filesystem store for media bytes (no object
storage, no message queue, no vector database, no background worker/task
queue introduced). See `docs/architecture/ARCHITECTURE_DECISIONS.md` for
Phase 1's 7 recorded decisions (all still in force), `docs/architecture/EDGE_ARCHITECTURE.md`
for Phase 8's architectural map, and `docs/architecture/FLEET_MANAGEMENT.md`
for this phase's own. Phase 9's own additions:

- **Four new primary-entity tables, zero duplication of Phase 8's `Device`/
  `DeviceHealthReport` shapes.** `FleetSite` (deployment grouping, reusing
  `GeoLocationMixin`), `DeviceCapability` (five independent per-capability
  states), `DeviceConfigBaseline` (append-only administrative config
  intent), `InfrastructureAlert` (deduplicated fleet-health alert queue).
  Five new columns on the existing `devices` table (`site_id`,
  `config_revision`, `config_baseline_id`, `current_config`,
  `last_resource_metrics`). One Alembic migration
  (`3d7c5b9aa4e4_phase9_enterprise_fleet_management`), needing the same
  two SQLite-specific fixes Phases 6 and 8's migrations already needed
  (safe `server_default`s on new `NOT NULL` columns; `batch_alter_table`
  for the two new foreign keys on the existing `devices` table).
- **Presence is computed, never stored** -- `fleet_presence_service.derive_presence_state()`
  reads `Device.last_seen_at` fresh on every call; there is no
  `presence_state` column anywhere, deliberately, so it can never go
  stale relative to the `last_seen_at` it is derived from.
- **Three binding measurement-quality rules enforced structurally, not
  just by convention** -- `fleet_health_service.evaluate_health_findings()`
  only produces a finding for a metric the device actually reported
  (never a fabricated 0/100), stamps every finding with the `as_of`
  timestamp of the data it came from, and tags every finding's `source`
  as `device_reported` or `server_computed`.
- **Capability discovery's five states are genuinely independent** --
  `DeviceCapability.healthy=None` means never verified, not unhealthy;
  absence of a finding is never treated as a negative one, the same
  discipline Phase 7's `GeoLocationMixin` established for missing
  coordinates.
- **Config drift is only ever evaluated against an explicit, assigned
  baseline** -- `fleet_config_service.compute_drift()` returns
  `evaluated=False, has_drift=None` when no baseline is assigned (or it
  was deleted), never a fabricated "no drift." Config updates use real
  optimistic concurrency (`expected_revision` vs. `Device.config_revision`,
  HTTP 409 on mismatch via `ConfigRevisionConflictError`).
- **Alert deduplication is enforced in the service layer, not a DB
  constraint** -- `fleet_alert_service._upsert_open_alert()`/
  `_auto_resolve_if_open()` key off a stable `dedup_key` per ongoing
  condition; a resolved condition's later recurrence creates a
  genuinely new row rather than silently reusing a closed one. Alerts
  are (re-)evaluated inline, on every health-report submission, by
  extending Phase 8's own `edge_sync_service.process_health_report()`
  -- never a second, parallel ingestion path or a background poller.
- **The extended lifecycle's two new states are reached only by
  deliberate, explicit administrative action** -- `maintenance`/
  `decommissioned` are never inferred from device-reported data, the
  same "explicit-only state" discipline Phase 6 established for
  `Sensor.lifecycle_status`'s own `maintenance`/`retired` additions.
  `decommission_device()` never deletes any historical `SyncRecord`/
  `DeviceHealthReport`/`AuditRecord` row.
- **The heartbeat rate limiter is a documented, best-effort,
  single-process, in-memory limiter** -- `fleet_presence_service.py`'s
  module-level dict, explicitly not multi-process-safe since this
  project has no shared cache/broker. Stated plainly as a known
  limitation, not hidden -- see `docs/security/DEVICE_LIFECYCLE_SECURITY.md`
  Section 6.
- **Fleet analytics is a live snapshot, never a stored trend** --
  `fleet_analytics_service.fleet_overview()` computes every figure fresh
  from currently-persisted rows at call time; nothing extrapolates a
  historical trend from a single snapshot.
- **No background scheduler anywhere in this project, including this
  phase** -- unchanged from every prior phase's own statement; alert
  (re-)evaluation is inline during health-report ingestion, never a
  timer.

Tenant isolation is still modeled but not enforced at the query-filter level
beyond what every service function already does explicitly (unchanged from
Phase 1, still Phase 14's job) -- every new fleet service function takes
`organization_id` as a required filter, matching every prior phase's own
per-call discipline; `test_fleet_overview_tenant_isolation` exercises this
directly for the new analytics endpoint.

## 3. Current phase status

**Phase 1-7: COMPLETE** (unchanged from prior phases). **Phase 8: COMPLETE**
(unchanged from Phase 8's completion, tested in simulation only). **Phase 9:
COMPLETE** as of this session, tested in simulation only.

| Area | Status |
|---|---|
| Presence derivation + heartbeat (reusing Phase 8's `last_seen_at`, kept separate from `connectivity_state`) | Implemented, tested |
| Health-finding rule engine (3 measurement-quality rules, 5 configurable-threshold rules) | Implemented, tested |
| Capability discovery (5 independent per-(device, capability) states) | Implemented, tested |
| Fleet sites/groups (reusing Phase 7's `GeoLocationMixin`) | Implemented, tested |
| Configuration baselines, optimistic-concurrency updates, drift detection | Implemented, tested |
| Infrastructure alerting (service-layer dedup, full ack/resolve/reopen lifecycle, audited) | Implemented, tested |
| Extended administrative lifecycle (`maintenance`/`decommissioned`) + confirmation preview | Implemented, tested |
| Fleet analytics (live overview snapshot) | Implemented, tested |
| Fleet API (6 new route modules, 5 new permissions) | Implemented, tested |
| Automated backend tests | 784 tests total (66 new this phase across 7 new test files), 93% line coverage, all passing |
| Frontend Fleet Operations Center | Overview/Sites/Alerts pages, plus device-detail capability/config/lifecycle/site-assignment extensions, built this phase and routed; independently verified via a clean `tsc`/`build`/`lint` pass (not a live browser click-through) |
| Documentation (6 new files + MASTER_ROADMAP/README/this file updated) | Written |

## 4. Capabilities: real vs. planned

**Real and working today, newly added in Phase 9:** server-computed
`presence_state` (online/stale/offline/unknown) derived purely from
`Device.last_seen_at`, exposed on every device read, never substituted
for Phase 8's own device-self-reported `connectivity_state`; a
rate-limited device heartbeat endpoint (`POST /edge/presence/heartbeat`)
that is server-authoritative about receipt time and rejects an
out-of-order/replayed `reported_at`; a health-finding rule engine
covering presence/disk/battery/queue-depth with configurable thresholds
and full `evidence`/`as_of`/`source` provenance on every finding; a
five-state capability model (three device-reported, two server-computed,
with `healthy=None` meaning never-verified rather than unhealthy) plus a
fleet-wide capability-summary rollup; `FleetSite` deployment groups with
per-site device/presence/alert summaries; `DeviceConfigBaseline`s with
real optimistic-concurrency config updates (a genuine HTTP 409 on a
stale revision) and key-by-key drift reporting that never claims "no
drift" without an assigned, existing baseline; a dedicated
`InfrastructureAlert` queue with real service-layer deduplication (an
open alert is updated in place on repeated detection, never duplicated;
a resolved condition's later recurrence creates a genuinely new row)
and a full open/acknowledged/resolved/reopened lifecycle with complete
audit trails on every human transition; an extended administrative
lifecycle (`maintenance`, `decommissioned`) with a read-only
confirmation-preview endpoint (`GET /devices/{id}/lifecycle-preview`)
that reports legality and concrete impact notes before any consequential
action is taken, and a verified guarantee that decommissioning never
deletes historical sync/health/audit rows; a live fleet-analytics
snapshot (`GET /fleet/analytics/overview`); and 5 new permissions with a
deliberate Investigator/Viewer split (`FLEET_SITE_READ`/
`INFRA_ALERT_READ`/`FLEET_ANALYTICS_READ` broadly granted, `*_MANAGE`
analyst/admin-only, device capability/config endpoints deliberately
reusing the existing `DEVICE_READ`/`DEVICE_MANAGE` permissions rather
than introducing new ones) -- all confirmed via a freshly re-run
automated test suite (784 passed, 93% coverage) and direct code reading
of every new file, not assumed from the phase's own scope description.

**Explicitly NOT built in Phase 9** (documented explicitly in each
relevant doc's "Known gaps"/"Known limitations" section): a
distributed/multi-process-safe heartbeat rate limiter (the shipped one
is single-process, best-effort, by design -- this project has no shared
cache/broker); any retention/purge job for `InfrastructureAlert`/
`DeviceCapability`/`DeviceConfigBaseline` (unchanged gap from Phase 8's
own `SyncRecord`/`SyncConflict`/`DeviceHealthReport`, all retained
indefinitely); a real external notification channel for infrastructure
alerts (none configured anywhere in this project); an evaluator for the
reserved `capability_unhealthy` alert type; any stored historical trend
series for fleet analytics (every figure is a live snapshot); alert
(re-)evaluation driven purely by inline heartbeat traffic alone (the
inline path is still only triggered from a full health-report
submission today, though the explicit `evaluate-sweep` endpoint now
covers presence/stale alerting independently of heartbeat traffic --
see Section 9); and a live browser click-through/Playwright
verification pass of the Fleet Operations Center frontend (the
frontend itself was built, routed, and independently verified via a
clean `tsc`/`build`/`lint` pass this phase; this documentation effort
stayed backend-and-docs-only, per its own
instructions, and did not build, modify, or drive the frontend).

## 5. Files created or modified this phase

- **Backend, new**: `app/models/fleet_site.py`, `device_capability.py`,
  `device_config_baseline.py`, `infrastructure_alert.py`;
  `app/services/fleet_presence_service.py`, `fleet_health_service.py`,
  `fleet_capability_service.py`, `fleet_config_service.py`,
  `fleet_alert_service.py`, `fleet_site_service.py`,
  `fleet_analytics_service.py`; `app/schemas/fleet.py`;
  `app/api/routes/edge_presence.py`, `fleet_sites.py`, `fleet_config.py`,
  `fleet_capabilities.py`, `infra_alerts.py`, `fleet_analytics.py`; 1
  Alembic migration (`3d7c5b9aa4e4_phase9_enterprise_fleet_management`);
  7 new test files (66 new tests): `test_fleet_presence.py` (12),
  `test_fleet_health_and_capabilities.py` (10),
  `test_fleet_config_and_drift.py` (7), `test_device_lifecycle_phase9.py`
  (8), `test_fleet_alerts.py` (11, including the three
  `evaluate-sweep` tests), `test_fleet_sites_and_analytics.py`
  (9), `test_fleet_routes_additional_coverage.py` (9).
- **Backend, modified**: `app/models/device.py` (5 new columns + the
  extended `DEVICE_ADMINISTRATIVE_STATUSES` tuple), `app/core/config.py`
  (11 new `FLEET_*` settings), `app/core/security.py` (5 new
  permissions: `FLEET_SITE_READ`/`FLEET_SITE_MANAGE`/`INFRA_ALERT_READ`/
  `INFRA_ALERT_MANAGE`/`FLEET_ANALYTICS_READ`), `app/main.py` (6 new
  routers), `app/services/device_service.py` (`enter_maintenance`,
  `decommission_device`, `preview_lifecycle_transition`, the extended
  `_ADMIN_ALLOWED_TRANSITIONS`/`CONSEQUENTIAL_LIFECYCLE_TRANSITIONS`),
  `app/services/edge_sync_service.py` (`process_health_report()` now
  also calls `fleet_capability_service.sync_from_health_report()` and
  `fleet_alert_service.evaluate_alerts_for_device()` inline),
  `app/api/routes/edge_devices.py` (new maintenance/decommission/
  lifecycle-preview/site/capabilities/config/config-baseline endpoints),
  `app/schemas/device.py` (`presence_state`, `site_id`, config fields on
  `DeviceResponse`; `DeviceSiteAssignRequest`).
- **Frontend, new (built by a separate, concurrent effort this
  phase, not by this documentation pass)**: `pages/fleet/FleetOverviewPage.tsx`,
  `FleetSitesPage.tsx`, `FleetAlertCenterPage.tsx`.
- **Frontend, modified (same concurrent effort)**: `App.tsx` (3 new
  routes under `/fleet/*`), `components/layout/AppShell.tsx` (3 new nav
  items: "Fleet Overview", "Fleet Sites", "Fleet Alerts").
- **Docs, new**: `architecture/FLEET_MANAGEMENT.md`,
  `architecture/DEVICE_HEALTH_MODEL.md`, `operations/FLEET_OPERATIONS.md`,
  `operations/INFRASTRUCTURE_ALERTS.md`,
  `security/DEVICE_LIFECYCLE_SECURITY.md`, `testing/FLEET_TESTING.md`,
  `implementation/PHASE_9_FINAL_REPORT.md`.
- **Docs, modified**: `implementation/MASTER_ROADMAP.md`, `README.md`,
  this file.

## 6. Database / migration status

- One new Alembic migration this phase:
  `3d7c5b9aa4e4_phase9_enterprise_fleet_management.py` -- creates 4
  new tables (`fleet_sites`, `device_config_baselines`,
  `device_capabilities`, `infrastructure_alerts`) and adds 5 columns to
  the existing `devices` table (`site_id`, `config_revision`,
  `config_baseline_id`, `current_config`, `last_resource_metrics`), plus
  2 new foreign keys on `devices`.
- **Two SQLite-specific fixes were needed**, the same discipline
  Phases 6 and 8's migrations already established: safe
  `server_default`s (`'0'`, `sa.text("'{}'")`) on the two new `NOT NULL`
  columns with no Python-side default (`config_revision`,
  `current_config`), and `op.batch_alter_table()` for the two new
  foreign keys on the existing `devices` table (SQLite cannot `ALTER
  TABLE ... ADD CONSTRAINT` directly). Both documented directly in the
  migration file's own module docstring.
- **Actually verified this session**: `alembic upgrade head` was
  applied to this session's real `backend/aegis.db`; the full automated
  test suite (which runs against its own fresh in-memory SQLite
  fixtures, independent of this migration) was re-run afterward and
  passed cleanly (Section 8).

## 7. Commands actually executed this session (not just written)

```
cd backend
source .venv/bin/activate
python -m pytest tests/ -q
  # 784 passed, 0 failed

python -m pytest tests/ -q --cov=app --cov-report=term-missing
  # 784 passed, 93% line coverage. Per-module coverage for new Phase 9
  # code: app/models/device.py 100%, app/models/device_capability.py
  # 100%, app/models/device_config_baseline.py 100%,
  # app/models/fleet_site.py 100%, app/models/infrastructure_alert.py
  # 100%, app/services/fleet_presence_service.py 100%,
  # app/services/fleet_site_service.py 100%,
  # app/services/fleet_config_service.py 97%,
  # app/services/fleet_analytics_service.py 97%,
  # app/services/fleet_capability_service.py 95%,
  # app/services/device_service.py 94%,
  # app/services/fleet_alert_service.py 92%,
  # app/services/fleet_health_service.py 88%, new route files 86-100%.
  # Full per-file test breakdown in docs/testing/FLEET_TESTING.md.
```

**No frontend commands (`tsc`/`eslint`/`npm run build`/Playwright) were
run as part of this documentation effort itself** -- this phase's own
documentation scope was backend-and-docs-only, stated honestly rather
than claimed. Those commands were run independently this phase, from
`frontend/` directly (`npx tsc -b`, `npm run build`, `npm run lint`),
and all passed cleanly (Section 3). The
frontend `pages/fleet/*` pages and device-detail extensions described
in Sections 3-5 were built concurrently by a separate effort in the
same repository during this same phase; their existence was confirmed
by a file listing and a grep of `App.tsx`'s route table, and they were
further confirmed by the clean `tsc`/`build`/`lint` pass above.

## 8. Test results (actually run, not assumed)

- **Backend:** `pytest tests/ -q --cov=app --cov-report=term-missing` →
  **784 passed**, 0 failed (718 from Phases 1-8, unchanged, + 66 new
  this phase across 7 new test files). **93% line coverage** across
  `app/`. Full per-file breakdown in `docs/testing/FLEET_TESTING.md`.
- **A real bug was found and fixed during this session's testing** --
  `fleet_capability_service._get_or_create()` could insert a duplicate
  row (tripping the `uq_device_capabilities_device_key` constraint)
  when the same `capability_key` appeared in both a health report's
  `runtime_capabilities` and `model_status` within one request, because
  every DB session in this project is `autoflush=False`. Fixed by
  flushing immediately after creating a new row. A related SQLite
  timezone-round-trip issue was fixed with the same `_aware()`
  normalization pattern `edge_sync_service.py` already established in
  Phase 8. Full detail: `docs/testing/FLEET_TESTING.md` Section 3.
- **No frontend live-browser/Playwright verification pass was
  performed this phase** -- unlike Phase 6/7/8's own live-verification
  bar, this phase's documentation effort did not drive the frontend in
  a browser, since the frontend itself was being built by a separate,
  concurrent effort and this phase's own instructions kept this work
  read-only against code and write-only against docs. That frontend
  *was* independently verified this phase via a clean `tsc`/`build`/
  `lint` pass run directly from `frontend/` (Section 7) -- stated
  explicitly rather than implied otherwise.

## 9. Known defects / limitations

**Found and fixed in this session:** the `fleet_capability_service`
duplicate-row race and the related SQLite timezone issue (Section 8),
both found and fixed during this session's own test-writing, not
discovered in already-"complete" code from a prior session.

**Still open / deliberately deferred (new this phase):**

- The heartbeat rate limiter (`fleet_presence_service.py`) is a
  documented, single-process, best-effort, in-memory limiter -- not
  multi-process-safe, since this project has no shared cache/broker.
  See `docs/security/DEVICE_LIFECYCLE_SECURITY.md` Section 6.
- No retention/purge job exists for `InfrastructureAlert`/
  `DeviceCapability`/`DeviceConfigBaseline` -- all retained indefinitely
  today, the same unchanged gap Phase 8 left for its own three tables.
- No real external notification channel (email/SMS) exists anywhere in
  this project for infrastructure alerts.
- The `capability_unhealthy` alert type is reserved in
  `INFRA_ALERT_TYPES` but has no current evaluator.
- Fleet analytics is a live snapshot only -- no stored historical trend
  series exists anywhere.
- Inline alert (re-)evaluation is still only triggered from a full
  health-report submission -- a device that only ever sends bare
  heartbeats will not get a `device_offline`/`device_stale` alert
  raised or auto-resolved purely from that inline traffic. This no
  longer leaves such alerts unraisable, though: the explicit
  `POST /fleet/alerts/evaluate-sweep` sweep (`evaluate_alerts_for_all_devices()`)
  evaluates every device's presence/health/drift state on demand,
  regardless of recent traffic, closing the gap `docs/architecture/
  FLEET_MANAGEMENT.md` Section 7 previously described as open.
- The Fleet Operations Center frontend has Overview/Sites/Alerts pages
  plus device-detail capability/config/lifecycle/site-assignment
  extensions (all built this phase); it was independently verified via
  a clean `tsc`/`build`/`lint` pass, but not via a live browser
  click-through.
- This entire phase inherits Phase 8's own simulation-only status --
  no physical edge hardware is available in this environment.

**Still open from Phase 1-8 (unchanged, not re-verified this phase):**

- Tenant isolation modeled, not enforced at a framework level (Phase 14).
- `docker-compose.yml` / Dockerfiles remain unexecuted in this sandbox (no
  Docker daemon available here).
- Refresh tokens are not revocable; `npm audit` vulnerabilities in frontend
  toolchain deps not reviewed. No live external HTTP source has ever been
  connected.
- `POST /assessments/{id}/supersede` still has no API route (Phase 3,
  unchanged).
- No second real deep-learning CV adapter (Phase 4, unchanged).
- No motion-prediction (Kalman) filter, no HOTA/IDF1/MOTA computation, no
  second tracker implementation, no per-frame extracted-image endpoint
  (Phase 5, unchanged).
- `Permission.SENSOR_QUALITY_REVIEW` defined but required by zero routes
  (Phase 6, unchanged).
- No spatial index/PostGIS integration, no coordinate-system conversion
  pipeline, no track-visualization integration with Phase 5's tracks, no
  live/streaming position feed (Phase 7, unchanged).
- An accepted `SyncRecord` is not automatically materialized into a
  canonical `Event`/`Observation`/`Evidence` row; no automatic
  retention/purge job for `SyncRecord`/`SyncConflict`/
  `DeviceHealthReport`/the local outbox; `retryable_failure` real but
  hard to reproduce under this project's synchronous architecture; only
  one synthetic edge-inference adapter exists; no background scheduler
  exists anywhere in this project (Phase 8, unchanged).

## 10. Configuration requirements

Unchanged from Phase 1-8 (`backend/.env.example`, the
`ENVIRONMENT=production` + real `SECRET_KEY` requirement, all `CV_*`/
`TRACKING_*`/`SENSOR_*`/`GEOSPATIAL_*`/`EDGE_*` settings). New in Phase
9, all with safe defaults (see `app/core/config.py`):
`FLEET_PRESENCE_STALE_AFTER_SECONDS` (120.0),
`FLEET_PRESENCE_OFFLINE_AFTER_SECONDS` (600.0),
`FLEET_HEARTBEAT_MIN_INTERVAL_SECONDS` (5.0),
`FLEET_HEALTH_DISK_WARNING_PCT` (80.0), `FLEET_HEALTH_DISK_CRITICAL_PCT`
(95.0), `FLEET_HEALTH_BATTERY_WARNING_PCT` (20.0),
`FLEET_HEALTH_BATTERY_CRITICAL_PCT` (5.0),
`FLEET_HEALTH_QUEUE_DEPTH_WARNING` (500),
`FLEET_HEALTH_QUEUE_DEPTH_CRITICAL` (2000),
`FLEET_ALERT_MAX_PAGE_SIZE` (200),
`FLEET_CAPABILITY_RECENTLY_VERIFIED_WINDOW_SECONDS` (3600.0). No new
backend third-party dependency. No new frontend third-party dependency.

## 11. External integrations

None connected -- unchanged from Phase 2-8. No real external
notification channel (email/SMS) is wired up anywhere for infrastructure
alerts, and no outbound call to any real external network, service, or
physical device exists anywhere in this phase's code.

## 12. Next steps for Phase 10

1. Read this file, `docs/implementation/MASTER_ROADMAP.md`'s Phase 10
   row and its "Phase 10 preview" section, and
   `docs/implementation/history/PHASE_9_FINAL_REPORT.md` before writing any code.
2. Do not re-implement or duplicate `RiskAssessment`, `ModelRecord`, or
   `ModelEvaluationRun` (Phase 1/4, already real and working) -- extend
   them, following every prior phase's own "extend, don't duplicate"
   discipline, for model-confidence/uncertainty-quantification/human-
   review work.
3. If Phase 10 (or any later phase) needs a device's own fleet-health
   signal (presence, capability, alert) as an input to a risk/
   confidence computation, reuse `fleet_health_service.py`/
   `fleet_alert_service.py` rather than re-deriving it.
4. If Phase 10 or a later phase needs a distributed-safe rate limiter,
   a retention/purge job, or a real external notification channel for
   any part of the fleet-management subsystem, those are reasonable,
   explicitly-flagged gaps to finally close -- see
   `docs/security/DEVICE_LIFECYCLE_SECURITY.md` Section 6 and
   `docs/operations/INFRASTRUCTURE_ALERTS.md` Sections 1 and 5.
5. The Fleet Operations Center frontend (overview/sites/alerts pages
   and device-detail capability/config/lifecycle/site-assignment
   extensions) was built this phase and independently verified via a
   clean `tsc`/`build`/`lint` pass; a live browser click-through/
   Playwright verification pass was not performed and remains a
   reasonable next step for whoever picks this up -- that should be
   documented as its own real, verified work when it happens, not
   implied to have happened in this phase.
6. This file must be updated again at the end of Phase 10, in place,
   following the same "only claim what was actually run" discipline.


## Where Phase 14 leaves the foundation

Phase 14 adds a tested security and governance slice (see `docs/security/` -- AUTHENTICATION_AND_AUTHORIZATION, ORGANIZATION_ISOLATION,
AUDIT_GOVERNANCE, DATA_CLASSIFICATION, DATA_LIFECYCLE, FILE_AND_EXPORT_SECURITY, ENVIRONMENT_CONFIGURATION, OPERATIONAL_SECURITY_CHECKS,
KNOWN_RISKS and `docs/implementation/history/PHASE_14_FINAL_REPORT.md`): per-user session revocation (`token_version`), password policy and change/reset
flows, last-admin protection, denied-access auditing, foreign-organization reference checks, immutable-audit guard (ORM + DB triggers, not
tamper-proof), a request/approve/execute data-lifecycle workflow with dry-run, request-size limits and security headers, production start
blockers, PyJWT replacing python-jose, and admin UI (access, audit explorer, lifecycle, security config). Not implemented: refresh-token
rotation, MFA, row-level security/composite tenant FKs, audit hash-chaining, encryption at rest, container scanning, Postgres trigger execution.
Next: Phase 15 should close the highest items in `KNOWN_RISKS.md`.

## Where Phase 15 leaves the foundation
Phase 15 adds MLOps and observability on top of the existing registry (see `docs/ml/MLOPS_ARCHITECTURE.md`): migration `b15e0ps0001` (head; revises `a14c0de5ec01`) adds owner/lifecycle/artifact columns to `model_records` and the tables `model_lifecycle_events`, `experiment_runs`, `experiment_baselines`, `monitoring_snapshots`, `review_signals`; 24 new API paths under `/api/v1/mlops` and `/api/v1/observability`; new permissions `mlops:read|register|run|review|monitor|approve` and `observability:read`; five frontend views. Verified: backend suite 1283 passed (1152 before; 131 new); migration upgrade/downgrade/upgrade with legacy-data backfill on SQLite; frontend `tsc -b`, eslint (0 errors) and `vite build`; headless-browser load of all five views against a live backend with no console errors. Known gaps: no serving/activation, no job queue, no frontend test runner, Postgres untested for the new migration.


## Where Phase 16 leaves the foundation
Phase 16 adds a shared analytics layer, three dashboards and a report builder (see `docs/analytics/ANALYTICS_ARCHITECTURE.md`, `METRIC_DEFINITIONS.md`, `docs/api/REPORTING_API.md`): migration `c16r3p0rt01` (head; revises `b15e0ps0001`) adds `report_runs` and seven windowed-query composite indexes; 93 catalogued metrics across 11 sections; 9 API paths under `/api/v1/reporting`; permissions `reporting:read`, `report:generate`; templates platform_activity, ingestion_quality, sensor_coverage, investigation_summary, evidence_provenance, model_evaluation, system_reliability, geospatial_summary, custom; JSON/CSV/HTML export (no PDF); four frontend views (executive, analyst, operations, reports). Verified: backend suite 1328 passed (1283 before; 45 new); migration from an empty DB to head, and downgrade/upgrade round trip with existing data on SQLite; frontend `tsc -b`, eslint (0 errors, 2 pre-existing warnings) and `vite build`; a headless-browser + API end-to-end run, 21/21 checks. Not delivered: PDF, AI-written summaries, async generation, uptime/queue-depth telemetry, saved report definitions/schedules, frontend automated test runner, Postgres execution of the migration.


## Where Phase 17 leaves the foundation
Phase 17 changed no schema (migration head is still `c16r3p0rt01`). Code fixes: `require_device_auth` returns 401 (not 422) for missing device credentials; the 422 handler no longer echoes submitted values (previously a mistyped login body could reflect a password). New tests: `test_integration_{workflows,sweeps,integrity,errors,jobs,migrations}.py`, `test_frontend_contract.py`. New tooling: `.github/workflows/ci.yml` (never run on GitHub), `backend/scripts/benchmark_queries.py`. Suite: 1363 passed, 94% line coverage; frontend `tsc -b` clean, `eslint` 0 errors / 2 pre-existing warnings, `vite build` OK; Phase 16 browser E2E re-run 21/21. Inventory and statuses: `docs/architecture/INTEGRATION_INVENTORY.md`; commands: `docs/testing/INTEGRATION_TESTING.md`; new risks 32-38 in `docs/security/KNOWN_RISKS.md`. Next: Phase 18 (final hardening and handoff); highest-value carry-overs are PostgreSQL verification, a background job queue, the React Router upgrade and frontend component tests.


## Where Phase 18 leaves the foundation
No schema change (head `c16r3p0rt01`). Release engineering added: `docker-compose.yml` / Dockerfiles / `.env.example` (unverified: images not built), `.github/workflows/ci.yml` (never run on GitHub), operations docs under `docs/operations/` (deployment, administrator, backup/restore, runbooks, configuration reference, release verification), and scripts `bootstrap_admin.py`, `backup_restore.py`, `smoke_test.py`, `check_schema_drift.py`, `gen_config_reference.py`, `e2e_release_browser.py`. Defects fixed: PostgreSQL 500 on `GET /sensors?measurement_type=`, false readiness 503 under concurrent probes, no first-admin path in production, frontend error boundary / session expiry. Evidence and the release decision (conditionally ready; native single-host PostgreSQL verified, containers/CI unverified) are in `docs/operations/RELEASE_VERIFICATION.md` and `history/PHASE_18_FINAL_REPORT.md`. New risks 39-48 in `KNOWN_RISKS.md`. This is the last phase of the planned roadmap; remaining work is listed in the final report.
