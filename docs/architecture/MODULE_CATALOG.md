# Module Catalog — AEGIS

Phase 1's 12 logical backend modules, plus 2 more added by Phase 2 (data
quality/observability and event correlation — modules 13-14), plus 5 more
added by Phase 3 (evidence, evidence relationships, conflict detection,
assessment, fusion orchestration — modules 15-19), plus the remaining 8
documented extension points for later phases. "Logical module" means a set
of files with one responsibility (typically `models/X.py` + `schemas/X.py`
+ `services/X_service.py` + `api/routes/X.py`), not a separate process.

## Implemented modules (Phase 1)

### 1. Authentication and authorization
- **Responsibility**: login, token issuance/refresh, password hashing,
  the `Permission`/`Role` model, the `require_permission` route
  dependency, login-failure/lockout handling.
- **Owned data**: none directly (operates on `User`).
- **Main APIs**: `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`,
  `GET /api/v1/auth/me`.
- **Dependencies**: User module.
- **Authorization**: `/login` and `/refresh` are unauthenticated by
  nature; `/me` requires a valid token.
- **Status**: IMPLEMENTED — real bcrypt hashing, real JWT issuance/
  verification, real lockout after `MAX_FAILED_LOGIN_ATTEMPTS`.
- **Future extension**: token revocation list, SSO/OIDC.

### 2. User and organization management
- **Responsibility**: user CRUD, role assignment, organization record.
- **Owned data**: `User`, `Organization`.
- **Main APIs**: `GET/POST /api/v1/users`, `GET/PATCH /api/v1/users/{id}`.
- **Dependencies**: Authentication module (for `require_permission`).
- **Authorization**: `USER_MANAGE` permission (administrator only by
  default `ROLE_PERMISSIONS`).
- **Status**: IMPLEMENTED.
- **Future extension**: multi-organization tenant isolation (Phase 14).

### 3. Data-source registry
- **Responsibility**: register/manage the sources events and
  observations come from; track reliability metadata and last
  ingestion attempt/success; enable/disable; explicit reliability-weight
  changes with a required reason; connector config validation and
  connectivity checks.
- **Owned data**: `DataSource` (Phase 2 adds `owner_team`,
  `connection_mode`, `enabled`, `last_error_category`, `config_revision`,
  `last_checkpoint_cursor`/`_at`, `reliability_weight`).
- **Main APIs**: `GET/POST /api/v1/sources`, `GET/PATCH /api/v1/sources/{id}`,
  `POST /api/v1/sources/{id}/enable|disable`,
  `PUT /api/v1/sources/{id}/reliability`,
  `POST /api/v1/sources/{id}/validate-config|check-connectivity|run`.
- **Status**: IMPLEMENTED, extended in Phase 2 — real connector
  implementations now exist (`app/connectors/`: `http_api`,
  `synthetic_demo`, plus the file-upload `json`/`csv` connectors); see
  `docs/architecture/CONNECTOR_ARCHITECTURE.md`. Reliability weight is
  still a human-set configuration value, never computed — see
  `docs/analytics/SOURCE_RELIABILITY.md`.
- **Future extension**: computed reliability scoring from fusion history --
  explicitly confirmed STILL not built in Phase 3 either (see
  `docs/analytics/CONFIDENCE_AND_SOURCE_RELIABILITY.md`); additional
  connector types (message queues, streaming feeds).

### 4. Event management
- **Responsibility**: canonical event storage, list/detail/filter/
  paginate; provenance and correlation lookups.
- **Owned data**: `Event` (Phase 2 broadens `data_origin` to include
  `"external_source"`, and `provenance` now carries
  `raw_record_id`/`connector_type`/`normalization_version`/etc.).
- **Main APIs**: `GET /api/v1/events`, `GET /api/v1/events/{id}`,
  `GET /api/v1/events/export`, `GET /api/v1/events/{id}/raw-record`,
  `GET /api/v1/events/{id}/correlations`.
- **Status**: IMPLEMENTED, extended in Phase 2 — events are still
  created only via the ingestion pipeline (module 5) or seed data, never
  a raw "create event" POST, because every event must carry real
  provenance (Rule 9). Export is permission-gated separately
  (`DATA_EXPORT`) and row-bounded — see `docs/api/INGESTION_API.md`.
- **Future extension**: Phase 3 added evidence/relationship/conflict/
  assessment linkage around events (modules 15-19 below) without changing
  `Event` itself at all — any still-deeper linkage remains out of scope.

### 5. Ingestion job management
- **Responsibility**: JSON/CSV upload validation, normalization,
  duplicate detection, event creation, job-state tracking with
  accepted/rejected/skipped/duplicate counts; connector-driven ("run
  source") batches through the same engine; retry of a connector-driven
  job; raw-record provenance listing.
- **Owned data**: `IngestionJob` (Phase 2 adds `trigger_type`,
  `retry_count`, `correlation_id`), `RawRecord` (new in Phase 2).
- **Main APIs**: `POST /api/v1/ingestion/jobs`, `GET /api/v1/ingestion/jobs`,
  `GET /api/v1/ingestion/jobs/{id}`,
  `GET /api/v1/ingestion/jobs/{id}/raw-records`,
  `POST /api/v1/ingestion/jobs/{id}/retry`.
- **Status**: IMPLEMENTED, rewritten in Phase 2 on a single shared
  `_process_batch()` engine (`app/services/ingestion_service.py`) used by
  both file-upload and connector-driven runs. Real validation
  (`validation_service.py`), real normalization (`normalization_service.py`),
  real duplicate detection with a SAVEPOINT-protected DB race backstop
  (`docs/data/DEDUPLICATION_POLICY.md`), real per-record provenance
  (`docs/data/DATA_PROVENANCE.md`).
- **Future extension**: scheduled/streaming ingestion (a connector that
  fetches on its own schedule rather than only via an explicit `/run`
  call) remains Phase 3-adjacent future work; this module's pull-based
  foundation is what such a scheduler would call into.

### 6. Asset registry
- **Responsibility**: track entities of interest (people, vehicles,
  facilities, equipment — whatever `entity_type` the analyst needs)
  with optional location/metadata.
- **Owned data**: `Asset`.
- **Main APIs**: `GET/POST /api/v1/assets`, `GET/PATCH /api/v1/assets/{id}`.
- **Status**: IMPLEMENTED.

### 7. Observation and sensor interfaces
- **Responsibility**: sensor registry (identity, type, status,
  last-seen) and the observation record shape sensors report into.
- **Owned data**: `Sensor`, `Observation`.
- **Main APIs**: `GET/POST /api/v1/sensors`, `GET/PATCH /api/v1/sensors/{id}`,
  `GET /api/v1/observations`.
- **Status**: IMPLEMENTED as a *foundation* — registry + storage shape
  are real; there is no sensor-health computation, no cross-source
  association, no quality scoring yet (that's Phase 6). Observations
  can be created via seed data for demonstration; no live sensor feed
  exists (Rule 9).

### 8. Investigation and case management
- **Responsibility**: case lifecycle, linked events, resolution notes.
- **Owned data**: `Investigation` (Phase 3 adds `purpose`, `scope`,
  `collaborator_user_ids`; `evidence_refs` can now hold real `Evidence.id`
  values from module 15 below, though no dedicated endpoint links them yet).
- **Main APIs**: `GET/POST /api/v1/investigations`,
  `GET/PATCH /api/v1/investigations/{id}`.
- **Status**: IMPLEMENTED.
- **Future extension**: a dedicated investigation<->evidence linking
  endpoint (today `evidence_refs` is a free-form JSON list, not validated
  against module 15's `Evidence` table the way `AssessmentEvidenceLink`
  validates its references); full analyst-notes/report generation
  (Phase 11).

### 9. Risk-assessment records
- **Responsibility**: store assessment records with explicit
  method/model-version, score, confidence, contributing factors,
  evidence references, and human-review status.
- **Owned data**: `RiskAssessment`.
- **Main APIs**: `GET /api/v1/risk-assessments`,
  `GET /api/v1/risk-assessments/{id}`,
  `POST /api/v1/risk-assessments/{id}/review`.
- **Status**: IMPLEMENTED as a *storage and review-workflow* shape only
  — seed data creates example records with
  `method = "seed_example_v0"` and an explicit confidence value, but
  there is no real scoring model. Creating a new assessment via the API
  is intentionally not exposed yet, because nothing in this phase can
  honestly produce one (Rule 3) — that's Phase 10.

### 10. Audit logging
- **Responsibility**: append-only record of who did what, when, with
  what outcome.
- **Owned data**: `AuditRecord`.
- **Main APIs**: `GET /api/v1/audit` (restricted).
- **Status**: IMPLEMENTED — real writes on every user/source/
  investigation/ingestion mutation; no update or delete route exists
  for audit records, by design. Documented explicitly in
  `docs/security/SECURITY_BASELINE.md` as an append-only *application*
  log, not a cryptographically tamper-evident one (Section 16's
  required distinction).

### 11. System health and operational status
- **Responsibility**: liveness/readiness, DB connectivity check.
- **Owned data**: none.
- **Main APIs**: `GET /api/v1/health/live`, `GET /api/v1/health/ready`.
- **Status**: IMPLEMENTED — `ready` actually executes a trivial query
  against the real configured database; it does not return `ready`
  unconditionally.

### 12. Dashboard aggregation
- **Responsibility**: read-only counts/summaries across the other
  modules for the Overview page.
- **Owned data**: none (aggregates others).
- **Main APIs**: `GET /api/v1/dashboard/summary`.
- **Status**: IMPLEMENTED — every number is a real `COUNT`/aggregate
  query against the real database, never a hardcoded figure (Rule 3,
  Section 11 "do not invent metrics").

## Implemented modules (Phase 2 additions)

Modules 3-5 above were extended in place; the two below are new logical
modules introduced by Phase 2.

### 13. Data quality and observability
- **Responsibility**: on-the-fly aggregate reporting over ingestion
  outcomes and raw-record validation status — never a stored/cached
  summary, always computed from the current table state.
- **Owned data**: none (aggregates `RawRecord`/`IngestionJob`).
- **Main APIs**: `GET /api/v1/data-quality/summary`,
  `GET /api/v1/data-quality/jobs-summary`.
- **Status**: IMPLEMENTED (new in Phase 2) — see
  `app/services/quality_service.py`.

### 14. Event correlation
- **Responsibility**: deterministic, rule-based, fully-explainable
  candidate-relationship detection between existing events for analyst
  review. Never a merge, never an automatic promotion.
- **Owned data**: `EventCorrelation`.
- **Main APIs**: `GET /api/v1/correlation`, `GET /api/v1/correlation/{id}`,
  `POST /api/v1/correlation/recompute`,
  `POST /api/v1/correlation/{id}/review`.
- **Status**: IMPLEMENTED (new in Phase 2) — see
  `app/services/correlation_service.py` and
  `docs/analytics/EVENT_CORRELATION.md`. Phase 3 adds one optional
  parameter (`time_window_seconds_by_type`) without otherwise changing
  this module — see module 19 and `docs/analytics/TEMPORAL_CORRELATION.md`.
- **Future extension**: ML-assisted/probabilistic correlation remains
  unbuilt — this module, and module 17 below, are deterministic and
  rule-based only; `model_assisted` is reserved vocabulary nothing writes
  yet (see `docs/analytics/CONFIDENCE_AND_SOURCE_RELIABILITY.md`).

## Implemented modules (Phase 3 additions)

Five new logical modules. See
`docs/architecture/INTELLIGENCE_FUSION_ARCHITECTURE.md` for the full
reused-vs-new rationale.

### 15. Evidence
- **Responsibility**: a bounded reference layer pointing at an existing
  Event/RawRecord/Observation, or carrying free analyst text/an external
  URI — never fetches or stores the content it references.
- **Owned data**: `Evidence`.
- **Main APIs**: `GET/POST /api/v1/evidence`, `GET/PATCH /api/v1/evidence/{id}`.
- **Status**: IMPLEMENTED (new in Phase 3) — see
  `app/services/evidence_service.py` and
  `docs/data/EVIDENCE_RELATIONSHIP_MODEL.md`.

### 16. Evidence relationships
- **Responsibility**: directional, multi-entity-type (event/evidence)
  links an analyst can draw by hand or a future rule-based generator can
  propose, with a confirm/reject/uncertain/reverse review workflow —
  deliberately distinct from module 14's event-only `EventCorrelation`.
- **Owned data**: `EvidenceRelationship`.
- **Main APIs**: `GET/POST /api/v1/relationships`,
  `GET /api/v1/relationships/{id}`, `GET /api/v1/relationships/{id}/history`,
  `POST /api/v1/relationships/{id}/review|reverse`.
- **Status**: IMPLEMENTED (new in Phase 3) — see
  `app/services/relationship_service.py` and
  `docs/data/EVIDENCE_RELATIONSHIP_MODEL.md`.

### 17. Conflict detection
- **Responsibility**: detect an actual, comparable disagreement between
  two events that already have a module-14 correlation row — never an
  independent all-pairs scan, never triggered by missing information.
- **Owned data**: `Conflict`.
- **Main APIs**: `GET /api/v1/conflicts`, `POST /api/v1/conflicts/detect`,
  `GET /api/v1/conflicts/{id}`, `GET /api/v1/conflicts/{id}/history`,
  `POST /api/v1/conflicts/{id}/resolve`.
- **Status**: IMPLEMENTED (new in Phase 3) — see
  `app/services/conflict_service.py` and
  `docs/analytics/CONFLICT_DETECTION.md`.

### 18. Intelligence assessment
- **Responsibility**: a bounded, versioned, evidence-cited analytical
  write-up with an enforced status lifecycle and qualitative-only
  confidence — never a computed conclusion.
- **Owned data**: `Assessment`, `AssessmentEvidenceLink`,
  `AssessmentRevision`.
- **Main APIs**: `GET/POST /api/v1/assessments`,
  `GET/PATCH /api/v1/assessments/{id}`,
  `GET /api/v1/assessments/{id}/revisions`,
  `GET/POST /api/v1/assessments/{id}/evidence`.
- **Status**: IMPLEMENTED (new in Phase 3) — see
  `app/services/assessment_service.py` and
  `docs/workflows/ASSESSMENT_LIFECYCLE.md`.
- **Future extension**: a `POST /assessments/{id}/supersede` route — the
  underlying `supersede_assessment()` function exists and is tested, but
  is not yet wired to an endpoint.

### 19. Fusion orchestration and evidence graph
- **Responsibility**: the one explicit, authorized entry point that
  composes module 14's correlation recompute with module 17's conflict
  detection into a single auditable `FusionJob`; plus a bounded,
  server-capped breadth-first traversal across events/evidence/
  assessments for analyst exploration.
- **Owned data**: `FusionJob` (the graph itself is computed on demand,
  never persisted).
- **Main APIs**: `POST /api/v1/fusion/run`, `GET /api/v1/fusion/jobs`,
  `GET /api/v1/fusion/jobs/{id}`, `GET /api/v1/fusion/graph`.
- **Status**: IMPLEMENTED (new in Phase 3) — see
  `app/services/fusion_service.py`, `app/services/graph_service.py`,
  `docs/analytics/EVIDENCE_GRAPH.md`.

## Documented extension points (not implemented — contracts only)

| Extension point | Owning future phase | Contract document |
|---|---|---|
| Computer-vision inference | Phase 4 | `COMPUTER_VISION_CONTRACTS.md` |
| Tracking and trajectory management | Phase 5 | `COMPUTER_VISION_CONTRACTS.md` |
| Geospatial analysis | Phase 7 | `GEOSPATIAL_CONTRACTS.md` |
| Edge synchronization | Phase 8 | `EDGE_SYNC_CONTRACTS.md` |
| Fleet management | Phase 9 | `EDGE_SYNC_CONTRACTS.md` |
| Retrieval and AI assistance | Phase 12 | `AI_ANALYTICS_CONTRACTS.md` |
| Scenario simulation | Phase 13 | `AI_ANALYTICS_CONTRACTS.md` |
| Model registry and evaluation | Phase 15 | `AI_ANALYTICS_CONTRACTS.md` |

No circular dependencies exist between modules: routes depend on
services, services depend on models, models depend only on `app.db.base`.
Nothing in `app/models/` imports from `app/services/` or `app/api/`.
