# AEGIS Master Roadmap — 18 Implementation Phases

This is the binding architectural guide for the full build. Later
phases may adjust *how* a phase is implemented based on real discoveries
made while building it, but a phase's intended capability must not
silently disappear from the roadmap — if something here turns out not
to be worth building, that decision gets written down (in
`docs/project/decisions.md` once it exists, or in this file), not
quietly dropped.

| # | Phase | Scope |
|---|---|---|
| 1 | **Enterprise Foundation** | Core architecture, shared data models, database, backend APIs, authentication, initial frontend, developer tooling. **This phase.** |
| 2 | Intelligence Data Platform | Source registry, import pipelines, event normalization, data validation, provenance, deduplication, ingestion jobs. |
| 3 | Multisource Intelligence Fusion | Event correlation, source reliability, temporal relationships, fusion services, conflict resolution, evidence lineage. |
| 4 | Computer Vision Infrastructure | Image/video processing interfaces, inference adapters, model metadata, media-job management, result schemas. |
| 5 | Tracking and Re-Identification | Track identities, track histories, confidence, trajectory storage, privacy-conscious identity matching. |
| 6 | Sensor and Observation Analytics | Sensor registry, observation ingestion, sensor health, observation quality, timestamp normalization, cross-source association. |
| 7 | Geospatial and Temporal Intelligence | Interactive maps, geospatial queries, event timelines, spatial clustering, geographic filtering, track visualization. |
| 8 | Edge AI and Offline Operation | Edge-agent interfaces, local inference abstractions, offline buffering, synchronization contracts, conflict handling. |
| 9 | Fleet Management and Device Observability | Device inventory, health telemetry, software/model version reporting, operational status, authorized configuration management. |
| 10 | Explainable AI and Risk Analytics | Anomaly detection, uncertainty estimates, interpretable assessments, evaluation metrics, model versioning, review workflows. |
| 11 | Investigations and Evidence Management | Case workflows, evidence references, analyst notes, review history, report generation, traceable conclusions. |
| 12 | Intelligence Copilot and Retrieval | Document ingestion, search, RAG where configured, citations, grounded summaries, refusal to invent missing evidence. |
| 13 | Simulation and Scenario Analysis | Synthetic scenario generation, configurable assumptions, event playback, sensitivity analysis, hypothetical-outcome comparison. |
| 14 | Security and Governance | Advanced authorization, audit controls, retention policies, security hardening, privacy controls, configuration validation. |
| 15 | MLOps and Observability | Model registry, evaluation records, model monitoring, data-quality monitoring, structured logs, metrics, operational diagnostics. |
| 16 | Advanced Analytics and Reporting | Cross-module analytics, historical comparisons, export, analyst reporting, configurable dashboards and saved queries. |
| 17 | Full System Integration | Cross-module integration, regression tests, contract tests, load testing where practical, reliability improvements, defect resolution. |
| 18 | Production Readiness and Delivery | Deployment, backup/recovery documentation, security review, performance validation, user documentation, demonstration workflow, acceptance report. |

## Where Phase 1 leaves the foundation

Phase 1 implements real, working, tested slices of: authentication and
authorization, user/organization management, the data-source registry,
event management, ingestion-job tracking (backing the Phase 2 pipeline,
pulled forward because Section 10 requires a first ingestion workflow
now), the asset registry, a sensor-registry foundation, investigation
and case management, risk-assessment records, audit logging, system
health, and dashboard aggregation — this matches Section 6's 12 logical
modules exactly.

It also writes **documented-but-unimplemented contracts** for the
subsystems later phases own: computer vision (Phase 4), multisensor
fusion and geospatial intelligence (Phases 3, 6, 7), edge sync (Phase 8),
and AI/analytics (Phases 10, 12, 13). These contracts describe shapes
and principles, not working code — see each contract doc's own status
line.

## Explicitly NOT built in Phase 1 (reserved for later phases)

- Any actual computer-vision inference, tracking, or re-identification
  (Phases 4–5).
- Any actual multisensor fusion logic or geospatial map rendering
  (Phases 3, 7) — the sensor registry and observation model exist; the
  fusion/correlation/mapping logic does not yet.
- Any edge-device agent, offline buffering, or sync protocol (Phases
  8–9) — the `Device` model and sync-contract document exist; nothing
  runs on an edge device.
- Any anomaly detection, explainability, retrieval/RAG, or scenario
  simulation (Phases 10, 12–13) — the `RiskAssessment` and `ModelRecord`
  models exist as storage shapes; no model produces a real score yet.
- Advanced governance beyond the Phase 1 security baseline, MLOps
  tooling, cross-module analytics/reporting, and the Phase 17–18
  integration/production work.

## Where Phase 3 leaves the foundation

Phase 3 (**Multisource Intelligence Fusion**, this phase) delivers a
real, working, tested vertical slice: evidence as a reference layer
(`Evidence`), directional analyst-and-rule-drawn relationships between
events and evidence (`EvidenceRelationship`, deliberately distinct from
Phase 2's `EventCorrelation`, which is reused unchanged), conflict
detection scoped to already-correlated pairs (`Conflict`), a bounded
and versioned analytical write-up (`Assessment` +
`AssessmentEvidenceLink` + `AssessmentRevision`), one explicit
orchestrated fusion run (`FusionJob`), and a bounded/explainable
evidence graph (`graph_service.py` + a frontend SVG/table view). See
`docs/architecture/INTELLIGENCE_FUSION_ARCHITECTURE.md` for the full
reused-vs-new breakdown and `docs/implementation/PROJECT_STATUS.md` for
this phase's complete status.

Source reliability, geospatial map rendering, and sensor-health
analytics remain exactly where Phase 1/2 left them — this phase's
"multisensor fusion" scope was interpreted as event/evidence-level
fusion (temporal/spatial/identifier correlation, conflict detection,
explainable assessment), not sensor-hardware-level health monitoring
(Phase 6's job) or map rendering (Phase 7's job).

## Explicitly NOT built in Phase 3 (reserved for later phases)

- Any ML-assisted or probabilistic relationship/conflict detection —
  `RELATIONSHIP_ORIGINS` reserves a `model_assisted` value that nothing
  in this phase writes (see `docs/analytics/
  CONFIDENCE_AND_SOURCE_RELIABILITY.md`).
- Any automated source-reliability scoring from fusion outcomes —
  `DataSource.reliability_weight` stays a human-set number with a
  mandatory reason, unchanged from Phase 2.
- A `POST /assessments/{id}/supersede` API route — the underlying
  service function exists and is tested, but is not yet wired to an
  endpoint (see `docs/workflows/ASSESSMENT_LIFECYCLE.md`).
- Any graph-rendering library/force-directed layout — the evidence
  graph is a from-scratch bounded SVG + accessible table, deliberately
  without adding a new frontend dependency.
- Geospatial map rendering, sensor health analytics, computer vision,
  tracking/re-identification, edge sync, explainable-AI model scoring,
  and every other phase this roadmap assigns to Phases 4–18 — unchanged
  from Phase 1/2's own statement of scope.

## Where Phase 4 leaves the foundation

Phase 4 (**Enterprise Computer Vision Infrastructure**, this phase)
delivers a real, working, tested vertical slice: secure, signature-
sniffed media ingestion into a private content-addressed store
(`MediaAsset`); a CV model registry that extends Phase 1's
`ModelRecord` rather than duplicating it, behind a closed, hand-written
adapter allow-list (`app/cv/adapters/registry.py`) that makes
arbitrary-code-execution-via-database-row structurally impossible; two
working adapters — a deterministic mock and a genuinely real, CPU-only
OpenCV HOG+SVM person detector, with the Ultralytics-YOLO alternative
explicitly evaluated and documented as not viable in this sandbox
(`docs/ml/MODEL_ADAPTERS.md`); synchronous image-detection and bounded
(sequentially-sampled, frame/duration-capped) video-frame-analysis
pipelines (`InferenceJob`), idempotent and boundedly retryable, same
lifecycle shape as Phase 2's `IngestionJob`/Phase 3's `FusionJob`;
real detection postprocessing — validation plus genuine
`cv2.dnn.NMSBoxes()` non-maximum suppression, never hand-rolled math —
producing `DetectionResult` rows with a fixed class-label allow-list
that structurally excludes any identity/biometric/hostile-intent
concept; an analyst review workflow that can promote a detection into a
real `Evidence` row (Phase 3) only when explicitly confirmed, enforced
in code; and deterministic model evaluation
(precision/recall/F1/mean-IoU, real IoU matching) against a seeded
synthetic fixture, always honestly flagged `is_synthetic=True`. See
`docs/architecture/COMPUTER_VISION_ARCHITECTURE.md` for the full
reused-vs-new breakdown and `docs/implementation/PROJECT_STATUS.md` for
this phase's complete status.

`docs/architecture/COMPUTER_VISION_CONTRACTS.md` (Phase 1's PLANNED
sketch for this phase) is now marked superseded for everything actually
built here, with its historical content kept unmodified for what
remains genuinely planned (`TrackIdentifier`/`TrackObservation`,
Phase 5's job).

## Explicitly NOT built in Phase 4 (reserved for later phases)

- Any tracking or re-identification across frames or media assets — no
  `track_id`-like concept exists anywhere in this schema; see
  `docs/architecture/COMPUTER_VISION_CONTRACTS.md`'s still-untouched
  `TrackIdentifier`/`TrackObservation` contracts (Phase 5's job).
- Any facial recognition, biometric identity matching, or automated
  person identification — both shipped adapters produce generic
  bounding boxes with a generic class label, never an identity signal,
  by design and by the fixed `ALLOWED_CLASS_LABELS` allow-list.
- Any hostile-intent, threat-level, or risk classification derived from
  a detection — a `DetectionResult`'s `confidence` is the model's own
  output confidence only, never collapsed into an interpretive score
  (the same "separated evidentiary concepts" discipline Phase 3
  established for `Evidence`/`Assessment`).
- Any real background worker or task queue for inference jobs — every
  job still runs synchronously inside its own API request, unchanged in
  spirit from Phase 2/3's own job-execution model.
- A second real deep-learning adapter (e.g. Ultralytics YOLO) — not
  installed in this sandbox; the registration procedure for adding one
  later is documented in `docs/ml/MODEL_ADAPTERS.md`.
- Any object-storage backend, retention policy, or per-organization
  storage quota for uploaded media (Phase 14/15's job, in part).
- Geospatial map rendering, sensor health analytics,
  tracking/re-identification, edge sync, explainable-AI model scoring,
  and every other phase this roadmap assigns to Phases 5–18 — unchanged
  from Phase 1/2/3's own statement of scope.

## Where Phase 5 leaves the foundation

Phase 5 (**Advanced Object Tracking, Track Lifecycle Management, Motion
Analytics, Trajectory Visualization, and Tracking Evaluation**, this phase)
delivers a real, working, tested vertical slice directly on top of Phase
4's `DetectionResult` rows: a reusable `ObjectTracker` interface with one
deterministic, dual-purpose (fixture + baseline) tracker
(`iou_hungarian_v1`) that associates detections via genuine IoU + a tested
Hungarian-assignment library call (`app/tracking/association.py`), never a
hand-rolled greedy sort and never a forced below-threshold match; explicit,
configurable track lifecycle states (`tentative`/`confirmed`/`missing`/
`reacquired`/`ended`/`rejected`) with every transition recorded and every
gap reconstructable, never interpolated; image-space-only motion analytics
in real pixels on each video's own measured resolution, with no speed or
predicted-position figure anywhere because a motion-prediction model was
deliberately deferred (Section 8 explicitly permits this); full lineage
persistence (`Track` → `TrackObservation` → `DetectionResult` →
`InferenceJob` → `MediaAsset`) behind a synchronous, idempotent, boundedly
retryable `TrackingJob`, same lifecycle shape as every prior job table in
this codebase; non-destructive analyst annotations (correct-via-supersede,
never edit/delete); and tracking evaluation using only this project's own
custom-defined metrics against a deterministic synthetic fixture, never
claiming HOTA/IDF1/MOTA without a trusted implementation (none exists in
this environment). A 10-route tracking API and a 7-page Tracking Analyst
Workspace (including a genuine `<video>` + live multi-track SVG overlay
component) expose all of this. See
`docs/architecture/OBJECT_TRACKING_ARCHITECTURE.md` for the full
reused-vs-new breakdown and `docs/implementation/PROJECT_STATUS.md` for this
phase's complete status.

`docs/architecture/COMPUTER_VISION_CONTRACTS.md`'s historical
`TrackIdentifier`/`TrackObservation` sketch is effectively superseded by
this phase's real `Track`/`TrackObservation` tables (named slightly
differently, same underlying idea) -- its content is left unmodified as the
historical record, consistent with how Phase 4 already treated that file
for its own scope.

## Explicitly NOT built in Phase 5 (reserved for later phases)

- Any facial recognition, biometric identification, or appearance-embedding-
  based re-identification — association is pure geometric IoU plus the
  detector's own class label, full stop; no pixel data or embedding ever
  reaches the tracker.
- Any cross-camera or cross-video identity matching — a `Track` is scoped to
  exactly one `TrackingJob`, scoped to exactly one source video; nothing
  anywhere links two jobs' tracks together.
- Any motion-prediction/Kalman filter — Section 8 explicitly permits
  deferring this when the baseline tracker doesn't need it; a track's "last
  known box" is always its most recent observed box, never a prediction.
  Reasonable Phase 6 (or later) follow-up if a future requirement justifies
  the added complexity.
- Any HOTA/IDF1/MOTA computation — no trusted MOT-metrics library installed
  in this environment; only this project's own custom, documented metrics
  are computed.
- Any hostile-intent, threat-level, or real-world-outcome classification
  derived from a track — `TRACK_STATES` has no such concept, by design.
- Any real background worker or task queue for tracking jobs — every job
  still runs synchronously inside its own API request, unchanged in spirit
  from every prior phase's own job-execution model.
- Any cancel endpoint for an in-flight tracking job — there is no separate
  in-flight state to cancel under this synchronous execution model.
- A second tracker implementation — the allow-list registry is ready to
  accept one without touching the service or API layer, but none exists yet.
- Any per-frame extracted-image endpoint — the frontend's video+track
  overlay plays the real stored video directly and overlays live per-frame
  data on top of it.
- Geospatial map rendering, sensor health analytics, edge sync,
  explainable-AI model scoring, and every other phase this roadmap assigns
  to Phases 6–18 — unchanged from Phase 1/2/3/4's own statement of scope.

## Where Phase 6 leaves the foundation

Phase 6 (**Sensor and Observation Analytics**, this phase) delivers a real,
working, tested vertical slice directly on top of Phase 1's `Sensor`/
`Observation` tables and Phase 2's `IngestionJob`/`RawRecord` job
machinery (both reused, not duplicated): a canonical observation-validation
layer (`app/sensors/quality.py` + `app/sensors/units.py`) that normalizes
timestamps, converts/validates measurement units against each sensor's own
declared operating range, and flags duplicate/stale/incomplete records
before a row is ever accepted as a canonical `Observation`; three
deterministic ingestion adapters — synthetic, CSV, and JSON — behind a
closed, hand-written registry (`app/sensors/adapters/registry.py`), the
same arbitrary-code-execution-proof allow-list discipline Phase 4's CV
adapters and Phase 5's trackers already established; an explicit sensor
lifecycle (`registered`/`active`/`degraded`/`offline`/`maintenance`/
`retired`) where `registered→active` happens automatically on first
accepted observation, `active↔degraded/offline` is computed by
`sensor_health_service.recompute_lifecycle_status()`, and `maintenance`/
`retired` are always explicit, audited analyst actions — never silently
computed; bounded, deterministically-downsampled time-series queries
(`app/services/timeseries_service.py`, 90-day/1000-sample caps) that always
disclose truncation/downsampling rather than hiding it; four statistical
anomaly-detection methods (rate-of-change, median-absolute-deviation,
rolling z-score, range violation — never a black-box ML model) whose
detected `category` is automatic but whose `review_status` is always an
explicit analyst action via `POST /sensor-analytics/anomalies/{id}/review`;
a four-signal sensor-health model (connectivity, measurement quality,
anomaly status, device-reported status) that is deliberately never
collapsed into one score, with every explanation string written to read as
"a statistical observation, never an automatic threat/hostility judgment";
and read-only cross-source observation comparison that can optionally
persist its result as an `EvidenceRelationship` (Phase 3's model, reused
unchanged). A 23-route sensor/analytics API surface and a 5-page Sensor
Intelligence Workspace (including a hand-rolled SVG time-series chart,
since this project has no charting library) expose all of this, the latter
confirmed via a live Playwright-driven browser session against the real
backend and real seeded data — not just `tsc`/`eslint`/`build`, a stronger
verification bar than Phase 5 used. See
`docs/architecture/SENSOR_DATA_ARCHITECTURE.md` for the full reused-vs-new
breakdown and `docs/implementation/PROJECT_STATUS.md` for this phase's
complete status.

`docs/architecture/MULTISENSOR_CONTRACTS.md`'s Phase 6 section (sensor
health computation, observation-quality scoring, timestamp normalization,
cross-source association — all previously `PLANNED`) is now superseded by
this phase's real implementation; its still-accurate Phase 3 section
(source reliability, fusion services, evidence lineage, already delivered
by Phase 3) is left unmodified, and the file itself is kept as the
historical record rather than deleted, consistent with how Phase 4/5
already treated their own superseded contract sketches.

## Explicitly NOT built in Phase 6 (reserved for later phases)

- Any automatic hostile-intent, threat, or equipment-fault determination
  derived from a sensor-health or anomaly signal — every one of the four
  health signals and every anomaly explanation string is phrased as a
  statistical observation for a human analyst to interpret, never a
  confirmed judgment, enforced as a binding wording discipline throughout
  `app/services/sensor_health_service.py` and `app/sensors/anomaly.py`.
- Any dedicated standalone "Data Quality Center" page — quality-flag/
  validation-status visibility was folded into the per-sensor Time-Series
  Explorer (point coloring by `validation_status`) and the Descriptive
  Statistics panel instead, since no backend endpoint exists for a
  cross-sensor aggregate quality view; a reasonable Phase 16 (cross-module
  analytics/reporting) follow-up if a future requirement justifies a
  dedicated cross-sensor quality dashboard.
- Enforcement of `Permission.SENSOR_QUALITY_REVIEW` — the permission is
  defined and role-granted (Analyst, Investigator) but required by zero
  routes (confirmed by repository-wide search); documented honestly as a
  reserved-but-unused permission in `docs/security/SENSOR_DATA_GOVERNANCE.md`
  and `docs/api/SENSOR_API.md` rather than silently left unmentioned.
- Any real-time/streaming ingestion (WebSocket, MQTT, a message queue) — a
  sensor batch is submitted and processed synchronously inside its own API
  request, the same job-execution model every prior phase's job tables
  use; no background worker or task queue was introduced.
- Any automatic cross-sensor fusion or multi-sensor conclusion — cross-
  source comparison is read-only and advisory (a human-reviewed `compare`
  call, optionally persisted as a relationship); it never auto-merges two
  sensors' observations into a single derived value, consistent with
  `docs/architecture/MULTISENSOR_CONTRACTS.md`'s original binding principle
  against silently fusing observations across incompatible sources.
- Geospatial map rendering, edge sync, explainable-AI model scoring, and
  every other phase this roadmap assigns to Phases 7–18 — unchanged from
  Phase 1/2/3/4/5's own statement of scope.

## Where Phase 7 leaves the foundation

Phase 7 (**Geospatial and Temporal Intelligence**, this phase) delivers a
real, working, tested vertical slice directly on top of every
location-bearing table this project already had (`Event`/`Sensor`/
`Observation`/`Asset`, reused, not duplicated): `GeoLocationMixin` extended
with 7 provenance/uncertainty columns (coordinate reference system, origin,
validation status, positional uncertainty, altitude, altitude reference,
provenance note) across all four tables by one clean, autogenerated
migration; a pure-logic `app/geo/` package (`distance.py` — the single
shared haversine implementation, promoted from a private helper
Phase 2's `correlation_service.py` used to duplicate; `validation.py` —
coordinate/quality classification computed live on every read, never off a
stale stored column); bounded viewport and radius spatial queries with
correct antimeridian handling and an honest `truncated`/`total_matched`
contract on every response; bounded timeline queries powering real,
never-interpolated historical playback (the frontend steps through actual
stored records only); a location-quality reporting service that
distinguishes missing from invalid from uncertain as three genuinely
different concepts; rule-based spatial-relationship candidate generation
(`spatially_associated`, a value Phase 3's `EvidenceRelationship` model
reserved since Phase 3 and left unused until now) with a sliding-time-window
bound that keeps pairwise comparison far below O(n²), explicitly never
duplicating Phase 3's `conflict_service.py`'s same-real-world-event
determination and reviewed through that existing relationship-review
endpoint rather than a new one; bounded spatial-grid and temporal-gap
analytics that are counts only, never a threat/priority inference from
density or proximity; and CSV-injection-safe, bounded GeoJSON/CSV export
reusing Phase 2's own formula-prefix guard. A 13-route API surface and a
7-section Geospatial Intelligence Workspace (Overview, Interactive Map
Explorer with Leaflet-based clustering and a configurable, no-hardcoded-key
tile source, Timeline Explorer, Location Quality Center, Spatial
Relationship Explorer, Geographic Analytics Dashboard, Export Center)
expose all of this, confirmed via a live Playwright-driven browser session
against the real backend and real seeded data — including two real
interaction tests (confirming a spatial-relationship candidate; downloading
a real GeoJSON export) — the same live-verification bar Phase 6
established. See `docs/architecture/GEOSPATIAL_INTELLIGENCE_ARCHITECTURE.md`
for the full reused-vs-new breakdown and `docs/implementation/PROJECT_STATUS.md`
for this phase's complete status.

`docs/architecture/GEOSPATIAL_CONTRACTS.md` (Phase 1's `PLANNED` sketch
for this phase) is now marked superseded for everything actually built
here, with its content left unmodified as the historical record, consistent
with how Phase 4/5/6 treated their own superseded contract sketches.

## Explicitly NOT built in Phase 7 (reserved for later phases)

- Any autonomous targeting, engagement, or interception calculation of any
  kind — not part of this project's scope at any phase.
- Any automated hostile-intent or threat-level classification derived from
  geographic proximity, density, or clustering — every spatial/temporal
  analytic in this phase returns a count or a distance/time figure, never a
  score or label; see `docs/analytics/SPATIAL_TEMPORAL_ANALYTICS.md`
  Section 1.
- Any coordinate-system conversion pipeline (e.g. UTM-to-WGS84) — an
  `unsupported_crs` record's raw numbers are preserved, never converted;
  `SUPPORTED_COORDINATE_REFERENCE_SYSTEMS` remains `("WGS84",)` only.
- A spatial index or PostGIS integration — every query is a bounding-box
  pre-filter plus an exact in-Python haversine check, documented honestly
  as not benchmarked at a larger data volume than this project's own
  seeded/test data (see
  `docs/architecture/GEOSPATIAL_INTELLIGENCE_ARCHITECTURE.md` Section 4) —
  a reasonable Phase-17/18 (or an earlier Postgres migration) follow-up if
  a future deployment's data volume justifies it.
- Track-visualization integration with Phase 5's `Track`/`TrackObservation`
  tables — those remain image-space pixel trajectories over video, not
  georeferenced coordinates, out of this phase's scope.
- Any live/streaming position feed — every geospatial endpoint is a
  point-in-time read; no WebSocket, SSE, or polling-push surface exists
  anywhere in this subsystem.
- A bundled default map tile provider or API key — none exists anywhere in
  this codebase, by design; see `docs/operations/MAP_PROVIDER_CONFIGURATION.md`.
- Edge sync, explainable-AI model scoring, and every other phase this
  roadmap assigns to Phases 8–18 — unchanged from Phase 1/2/3/4/5/6's own
  statement of scope.

## Where Phase 8 leaves the foundation

Phase 8 (**Edge AI, Offline-First Operation, Durable Local Queues,
Conflict Resolution, and Safe Synchronization**, this phase) delivers a
real, working, tested vertical slice: `Device` (Phase 1's placeholder
shape, extended in place, not duplicated) gains a real identity/
credential/lifecycle registry — a globally-unique `device_identifier`,
`pending`/`active`/`suspended`/`revoked` administrative lifecycle, and
bcrypt-hashed, one-time-displayed, immediately-revocable API keys reusing
the exact same `hash_password`/`verify_password` functions user passwords
already use. A new `SyncRecord` model is the durable, idempotent CENTRAL
inbox for every sync attempt ever made, with a DB-level unique constraint
on `(organization_id, device_id, idempotency_key)` backing the idempotency
guarantee and an enforced transition table (`SYNC_RECORD_TRANSITIONS`)
that raises rather than silently allows an illegal state change. A
two-tier acceptance policy treats the three immutable record types as
append-only (a same-id/different-payload resubmission is quarantined for
human review, never merged) and the one mutable type (`annotation`) with
`base_revision`/`revision` optimistic concurrency, producing a new,
deliberately separate `SyncConflict` model (never Phase 3's `Conflict`)
on a mismatch — resolved only by an explicit, audited human decision
(`keep_central`/`keep_local`/`merged`), never last-write-wins. A simulated
edge runtime (`app/edge/`) provides a genuinely separate local SQLite
outbox (`LocalEdgeStore`, durability proven by closing and reopening the
same file), a real-HTTP (`httpx`) simulated device (`SimulatedEdgeNode`)
that talks to the real FastAPI application exactly as a physical device
would, and a closed, one-adapter synthetic inference registry whose
results are explicitly kept separate from sync state. Central ordering
for the one mutable type is always by central receipt order, never a
device's own clock. Crash-recovery sweeps exist on both sides but,
consistent with this project having no background scheduler anywhere, are
manually/externally triggered via API, never an automatic timer. A
4-route-file API surface (device-JWT-admin and device-credential-
authenticated routes, cleanly separated) and a 3-page Edge Operations
frontend (device registry/detail, sync queue, conflict review) expose all
of this, confirmed via a live end-to-end verification pass against real
running servers and real simulated device traffic — including a genuine
cross-device conflict resolved through the real UI and a genuine
quarantined integrity-failure record. See
`docs/architecture/EDGE_ARCHITECTURE.md` for the full reused-vs-new
breakdown and `docs/implementation/PROJECT_STATUS.md` for this phase's
complete status.

**Tested in SIMULATION ONLY — no physical edge hardware is available in
this environment.** `docs/architecture/EDGE_SYNC_CONTRACTS.md` (Phase 1's
`PLANNED` sketch for this phase) is now marked superseded for everything
actually built here, left unmodified as the historical record, consistent
with how Phase 4/5/6/7 treated their own superseded contract sketches.

## Explicitly NOT built in Phase 8 (reserved for later phases)

- Any autonomous targeting, weapon control, engagement decision, or
  remote weapon interface — not part of this project's scope at any
  phase; the one edge inference adapter is a synthetic brightness
  classifier, nothing resembling a weapons system.
- Automatic promotion of an accepted `SyncRecord` into a canonical
  `Event`/`Observation`/`Evidence` row — `SyncRecord` itself is this
  phase's durable, authoritative record of what was accepted; promoting
  it is an explicit, deferred Phase 9/17 follow-up, not a silent gap.
- Real fleet observability/dashboards beyond this phase's own device
  registry and sync/conflict queues — that is Phase 9's job (next,
  below).
- A second, trained edge-inference adapter, or any dynamic
  adapter/model-loading mechanism — the one synthetic adapter exercises
  the plumbing honestly; a real adapter is a future, purely-additive
  registry entry.
- Any automatic retention/purge job for `SyncRecord`/`SyncConflict`/
  `DeviceHealthReport`/the local outbox — all retained indefinitely
  today, an explicitly documented gap, not an invented policy.
- A background scheduler of any kind — crash-recovery sweeps are
  manually/externally triggered via API, consistent with every prior
  phase's request/response-only architecture.
- Any location/geospatial handling of its own — a future phase needing a
  device's own location reuses Phase 7's `GeoLocationMixin`/`app/geo/`
  rather than adding parallel logic.

## Where Phase 9 leaves the foundation

Phase 9 (**Enterprise Edge Fleet Management, Device Observability,
Health Monitoring, Capability Inventory, Lifecycle Management, and
Operational Dashboards**, this phase) delivers a real, working, tested
vertical slice directly on top of Phase 8's `Device`/`SyncRecord`/
`DeviceHealthReport` foundation (extended, never re-implemented):
server-computed presence derivation (`presence_state`) reading purely
from Phase 8's existing `Device.last_seen_at`, kept genuinely separate
from Phase 8's own device-self-reported `connectivity_state` so neither
is ever substituted for the other; a standardized health-finding rule
engine (`app/services/fleet_health_service.py`) with three binding
measurement-quality rules (missing data stays missing, stale vs. fresh
distinguished, device-reported vs. server-computed distinguished)
across five configurable-threshold rules; a `DeviceCapability` model
tracking five genuinely independent per-(device, capability) states --
three device-reported (`supported`/`installed`/`available_and_ready`)
and two server-computed (`healthy`/`last_verified_at`, where
`healthy=None` means never verified, never "unhealthy"); `FleetSite`
deployment groups reusing Phase 7's `GeoLocationMixin` rather than a
second coordinate pair; `DeviceConfigBaseline` with optimistic-
concurrency config updates (`expected_revision`, HTTP 409 on mismatch)
and key-by-key drift detection where a missing/deleted baseline is
never reported as "no drift"; a dedicated `InfrastructureAlert` queue
with service-layer deduplication by a stable `dedup_key` per ongoing
condition — deliberately separate from intelligence `Event`/
`ObservationAnomaly`/`RiskAssessment` alerting, auto-(re-)evaluated on
every health-report submission via Phase 8's existing ingestion path
and, for a device that goes genuinely silent, via an explicit
operator/cron-triggered `POST /fleet/alerts/evaluate-sweep` sweep,
with no real external notification sent; and an extended administrative
lifecycle adding `maintenance` (temporary, explicit, reversible,
distinct from Phase 8's security-suspicion `suspended`) and
`decommissioned` (permanent, explicit, non-security end-of-life,
distinct from Phase 8's security-response `revoked`, never deleting
historical sync/health/audit rows), with a read-only confirmation-
preview endpoint for every consequential transition. A live
point-in-time fleet-analytics snapshot (`GET /fleet/analytics/overview`)
rounds out this phase — deliberately with no stored trend series. A
6-route-module API surface and a Fleet Operations Center frontend
(overview/sites/alerts pages plus device-detail capability/config/
lifecycle/site-assignment extensions, built concurrently during this
same phase and independently verified via a clean `tsc`/`build`/`lint`
pass) expose this. See
`docs/architecture/FLEET_MANAGEMENT.md` for the full reused-vs-new
breakdown and `docs/implementation/PROJECT_STATUS.md` for this phase's
complete status.

**Tested in SIMULATION ONLY — no physical edge hardware is available in
this environment**, inherited directly from Phase 8's own standing
limitation.

## Explicitly NOT built in Phase 9 (reserved for later phases)

- Any autonomous targeting, weapon control, engagement decision, or
  remote weapon interface — not part of this project's scope at any
  phase; every new model/service/route this phase introduces concerns
  device inventory, health observability, capability inventory,
  configuration compliance, or fleet-health alerting only.
- A distributed/multi-process-safe heartbeat rate limiter — the
  shipped limiter is a documented, best-effort, single-process,
  in-memory one; this project has no shared cache or broker, and a
  real distributed limiter is a reasonable follow-up only if this
  backend is ever deployed with multiple worker processes.
- Any retention/purge job for `InfrastructureAlert`/`DeviceCapability`/
  `DeviceConfigBaseline` — unchanged from Phase 8's own still-open gap
  for `SyncRecord`/`SyncConflict`/`DeviceHealthReport`; all retained
  indefinitely today, a stated gap, not an invented policy.
- A real external notification channel (email/SMS) for infrastructure
  alerts — none is configured anywhere in this project; alerts surface
  only through the API/UI and the audit trail.
- An evaluator for the reserved `capability_unhealthy` alert type —
  the vocabulary is reserved in `INFRA_ALERT_TYPES`, but capability
  health is surfaced today only through the capability views, not
  through the alert queue.
- Any stored historical trend series for fleet analytics — the
  overview endpoint is a live snapshot only, by design.
- A full live-browser click-through/Playwright verification of the
  Fleet Operations Center frontend — this phase's own documentation
  effort was backend-and-docs only and did not drive the frontend in a
  browser. (The frontend itself, including the overview/sites/alerts
  pages and the device-detail capability/config/lifecycle tabs, was
  built this phase and independently verified via a clean
  `tsc`/`build`/`lint` pass.)
- Any location/geospatial handling beyond reusing Phase 7's
  `GeoLocationMixin` for `FleetSite` — unchanged from Phase 8's own
  statement of this discipline.

## Phase 10 preview: Explainable AI, Risk Analytics, Model Confidence, Uncertainty Quantification, Human Review, and Decision Support

Phase 10 builds on the `RiskAssessment`/`ModelRecord`/
`ModelEvaluationRun` scaffolding Phases 1–9 already established (none
of which Phase 9 touched) — expected scope: real model-confidence and
uncertainty-quantification reporting, interpretable/explainable
assessment write-ups, and human-review workflows over model output,
without inventing a second risk-scoring model where Phase 1's
`RiskAssessment` already reserves the shape. As with every prior phase,
Phase 10 must read this file, `docs/implementation/PROJECT_STATUS.md`,
and `docs/implementation/history/PHASE_9_FINAL_REPORT.md` first.

## Where Phase 10 leaves the foundation

Phase 10 is implemented as an explainable-analytics layer over existing records (see
`docs/architecture/EXPLAINABLE_ANALYTICS_ARCHITECTURE.md`): shared model-output schema,
classification/probability evaluation, faithful explanations with stated limits, advisory
review-priority scoring, and append-only human review. Anomaly detection, SHAP, calibrated
uncertainty estimates and model monitoring remain unbuilt (Phases 10-15 follow-ups). Next: Phase 11
(Investigations and Evidence Management).


## Where Phase 11 leaves the foundation

Phase 11 is implemented as a workspace over existing records (see `docs/architecture/INVESTIGATION_WORKSPACE.md`):
lifecycle + history, links, evidence registry/integrity/provenance, computed timeline, versioned notes, scoped search,
reproducible export. Deferred: retention/deletion policy, per-item evidence ACLs beyond a classification, pre-indexed
timeline/search for very large cases, cryptographic signing of exports, reviewer sign-off workflow, frontend tests and
browser verification. Next: Phase 12 (Intelligence Copilot and Retrieval) should retrieve over investigation records
through the same org/restriction checks (`investigation_service.get_accessible`) and never bypass them.


## Where Phase 12 leaves the foundation

Phase 12 adds keyword retrieval and a source-grounded copilot over existing records (see `docs/architecture/RETRIEVAL_COPILOT.md`).
Authorization is checked against live records at query time. Semantic search, a real model provider, background/change-triggered
indexing, OCR/document-upload extraction, shared (multi-worker) rate limiting and browser tests are deferred. Next: Phase 13 should
build on the retrieval/citation services rather than adding a second search path, and must keep the extractive path working with no provider.


## Where Phase 13 leaves the foundation

Phase 13 adds a bounded scenario-simulation workspace (see `docs/architecture/SCENARIO_SIMULATION.md`): three registered simulators on a
deterministic synthetic-data generator, scenario versioning, reproducible runs, what-if comparison and one-parameter-at-a-time
sensitivity analysis, all labelled simulated and isolated from operational data. Deferred: model-evaluation and assessment-parameter
simulators, cancellation/background execution, OS-level isolation, interaction (multi-parameter) sensitivity methods, retention for
stored runs/datasets, and browser tests. Next: Phase 14 (Security and Governance) should add retention/purge for simulated artifacts,
rate limits for compute-heavy endpoints, and review the audit/permission model across all 13 phases.


## Phase 14 -- Security and Governance: delivered (bounded slice)
Delivered: centralized-permission audit (253 gated routes), cross-org sweep, session revocation, password policy, audit governance,
lifecycle workflow, upload/request hardening, security config view, scanners script, docs under `docs/security/`.
Open items carried forward are listed in `docs/security/KNOWN_RISKS.md` (refresh rotation/MFA, RLS/composite tenant constraints,
external/hash-chained audit, remaining commit-before-audit services, encryption at rest, container and Postgres validation).

## Phase 15 -- MLOps and Observability: delivered (bounded slice)
Delivered: organization-owned immutable model versions with an audited lifecycle (registered → review_required → approved → deprecated → archived; evidence-gated approval, separate approver), reproducible experiment runs (fingerprints, idempotency, synchronous execution, honest undefined metrics, Wilson intervals), compatibility-checked baseline comparison with no overall verdict, monitoring snapshots with data-drift / prediction-drift / labelled-performance / operational sections, deduplicated review signals with acknowledge/resolve, an in-process metrics registry, JSON logging with redaction, error classification, authenticated detailed health, five frontend views, 131 new backend tests. Docs: `docs/ml/MLOPS_ARCHITECTURE.md`, `docs/ml/MLOPS_MONITORING.md`, `docs/operations/OBSERVABILITY.md`, `docs/implementation/history/PHASE_15_FINAL_REPORT.md`.
Not delivered / carried forward: model serving or activation environment, async jobs/queue, executing uploaded classifiers, real-data detection evaluation, cross-process metrics, frontend automated tests (no runner exists), Postgres validation of the migration. See `docs/security/KNOWN_RISKS.md` items 15–21.
Status of roadmap: Phases 1–15 delivered as bounded slices; 16–18 not started.


## Phase 16 -- Advanced Analytics, Reporting, Executive Dashboards: delivered (bounded slice)
Delivered: metric catalog and shared section layer (event vs ingestion time, half-open UTC windows, freshness, sample counts, missing-vs-zero, minimum-denominator rules, tenant/restricted-record/permission filtering before aggregation), geo k-suppressed grid, executive/analyst/operations dashboards with empty/loading/partial/stale/error/not-authorized states, report builder with validation, idempotency, private hashed storage, retention/purge, formula-injection-safe CSV and escaped HTML, audit of generate/download/expire.
Not delivered / carried forward: PDF, AI-written summaries, background/async generation, scheduled or saved reports, uptime and queue telemetry, per-user report sharing, encryption at rest for report files, frontend automated tests, Postgres validation (see KNOWN_RISKS 22-31).
Status of roadmap: Phases 1-16 delivered as bounded slices; 17-18 not started.

## Phase 17 -- Full System Integration: delivered (bounded slice)
Delivered: integration inventory with explicit verification status (`docs/architecture/INTEGRATION_INVENTORY.md`); exhaustive sweeps over all 319 API operations (auth, 5xx, viewer mutation, cross-tenant guessed ids, device credentials); static frontend↔backend contract test; executed cross-module workflows A-H; generic FK/tenant integrity checks; sanitized validation errors; job-status truthfulness tests; migration/ORM parity test; measured benchmark script; GitHub Actions workflow; dependency/static security review.
Not delivered / carried forward: PostgreSQL execution of any migration or test; real device/model/GPU verification; frontend unit/component tests; CI executed on GitHub; background job queue; React Router 7 upgrade; tolerant handling of stored invalid coordinates (see `KNOWN_RISKS.md` 33-38).
Status of roadmap: Phases 1-17 delivered as bounded slices; 18 delivered as a bounded slice (see below).

## Phase 18 -- Production Readiness and Delivery: delivered (bounded slice)
Delivered: hardened backend/frontend Dockerfiles (non-root, no migrate-on-start, readiness healthcheck), a compose file that requires secrets from `.env` with a one-shot `migrate` service, `scripts/bootstrap_admin.py` (first administrator in production), `scripts/backup_restore.py` (consistent DB+files backup, verify, non-destructive restore with post-restore verification), `scripts/smoke_test.py`, `scripts/check_schema_drift.py`, generated `docs/operations/CONFIGURATION_REFERENCE.md`, deployment guide, administrator guide, backup/restore guide and runbooks, CI jobs for PostgreSQL, security scanning and a container smoke test, a frontend error boundary and session-expiry handling, and fixes for defects found by running on real PostgreSQL and under concurrency (sensor JSON filter 500, readiness 503 race, device-auth 422).
Not delivered / carried forward: container images built and run; CI executed on GitHub; HA / multi-process correctness; background job queue; cookie sessions + CSP; encrypted-at-rest storage and backups; PostgreSQL full-suite green (27 fixture tests fail there, risk 44).
Status of roadmap: Phases 1-18 delivered as bounded slices. This does **not** mean production-ready for every environment; see `docs/operations/RELEASE_VERIFICATION.md` for the release assessment and `PHASE_STATUS_MATRIX.md` for per-phase status.

## Final stabilization pass (after Phase 18): release candidate 1.0.0-rc.1
No new phase and no schema change (head `c16r3p0rt01`). The 18 phases were re-verified on a clean
Windows 11 machine and repaired where that failed: seed/migration defect, runtime requirements,
ORM drift, a Python-3.14-only test failure, 429 error shape, page-level request defects, the CI
PostgreSQL job, React Router advisories, navigation/phone layout, stale UI text and documentation.
Per-subsystem status and next actions: `PROJECT_STATUS.md` ("Current state"); evidence and the
release checklist: `docs/operations/RELEASE_VERIFICATION.md`; release notes: `CHANGELOG.md`.

Remaining roadmap (post-1.0, in priority order): CI `postgres`/`containers` jobs green on GitHub
(release condition) → license (publication condition) → PostgreSQL-clean test fixtures → cookie
sessions + CSP → frontend component tests and bundle splitting → Tailwind 4 → background job queue
if needed → real model adapters/weights and hardware trials (out of scope for a synthetic-data demo).

## Consolidation pass (2026-10-18): proposed 1.0.0-rc.2
No new phase or migration. All phase archives were inventoried against git (nothing missing; see
an owner-only archive inventory kept outside the repository). Running the full suite on a real, non-UTC PostgreSQL 16 found
one application defect (analytics bucket labels, fixed) and 28 test-only problems (fixed). Added: CSP,
code splitting, frontend tests, release script, secret-scan baseline, CI hardening, publication guide.
Release gates now: owner commit → license decision → CI green on GitHub (including containers) → tag.
Status per subsystem: `PROJECT_STATUS.md`. Remaining post-1.0 work is unchanged in order, with the
PostgreSQL-fixture item done and "cookie sessions + CSP" reduced to "cookie sessions" (CSP shipped).

## Release candidate 2 (2026-10-19)
Owner decisions applied: MIT licence; react-leaflet replaced by plain Leaflet; a real pretrained detector
added. Delivered: SSD-MobileNet v1 COCO with SHA-256-verified weights and a real-image evaluation path
(COCO val2017 sample; mAP@0.5 0.461 vs HOG 0.003) in the API, MLOps and UI; HttpOnly cookie sessions;
UTC-correct timestamps on every database; Tailwind 4 (audit clean); orphan-file sweeper; key-rotation
grace period; code-quality cleanup (one UTC helper, no unused imports, no build-history narration, lint
0 warnings). Every KNOWN_RISKS defect is closed; six informational items remain.
Release gate: CI green on GitHub (including the never-built containers), then tag `v1.0.0-rc.2`.
Post-1.0 options: MFA; tamper-evident audit; shared rate-limit store; background job queue; a newer
detector through the same adapter contract.
