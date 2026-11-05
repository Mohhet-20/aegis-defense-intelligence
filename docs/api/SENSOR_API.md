# Sensor & Observation Analytics API (Section 10-11)

All routes are under `/api/v1`, and every one requires a bearer token and a specific
`Permission` checked server-side via `require_permission` -- same pattern as the other
modules' routes (`docs/api/TRACKING_API.md`, `docs/security/TRACKING_DATA_GOVERNANCE.md`).
Backed by `app/api/routes/sensors.py`, `app/api/routes/sensor_ingestion.py`,
`app/api/routes/sensor_analytics.py`, and `app/api/routes/cross_source_comparison.py`. Full
backend suite: 507 passed, 92% overall coverage, with `app/services/sensor_health_service.py`
at 97% and `app/services/cross_source_comparison_service.py` at 93%.

## Sensors (`app/api/routes/sensors.py`)

| Method & path | Permission | Notes |
|---|---|---|
| `GET /sensors` | `SENSOR_READ` | Paginated, filterable by `category`/`lifecycle_status`/`sensor_type`/`measurement_type`/`search`. |
| `POST /sensors` | `SENSOR_MANAGE` | Creates a `Sensor`; audit-logged (`sensor.create`). |
| `GET /sensors/{id}` | `SENSOR_READ` | `404` if not found or not in the caller's organization. |
| `PATCH /sensors/{id}` | `SENSOR_MANAGE` | Partial update (`exclude_unset=True`); audit-logged (`sensor.update`). |
| `GET /sensors/{id}/status-history` | `SENSOR_READ` | Returns `AuditRecord` rows for this sensor -- the same audit trail every mutating route writes to, surfaced here specifically for lifecycle/status changes. |
| `POST /sensors/{id}/lifecycle` | `SENSOR_MANAGE` | Explicit transition to a new `lifecycle_status` (one of `SENSOR_LIFECYCLE_STATUSES` in `app/models/sensor.py`: `registered`/`active`/`degraded`/`offline`/`maintenance`/`retired`); `400` via `InvalidLifecycleTransitionError` for a disallowed transition. |
| `POST /sensors/{id}/retire` | `SENSOR_MANAGE` | Dedicated terminal-state transition; `400` via `InvalidLifecycleTransitionError` if the sensor cannot be retired from its current state. |

## Sensor ingestion (`app/api/routes/sensor_ingestion.py`)

| Method & path | Permission | Notes |
|---|---|---|
| `POST /sensor-ingestion/batches` | `OBSERVATION_INGEST` | Multipart upload (`source_id` form field, `format` form field -- `json` or `csv` only, else `400`, `file`). `404` if the source doesn't exist; `409` if `source.enabled` is `False`; `413` via `BatchTooLargeError`. Audit-logged (`sensor_ingestion.run`) with accepted/rejected/duplicate counts and outcome derived from `job.status`. |
| `POST /sensor-ingestion/synthetic-batches` | `OBSERVATION_INGEST` | Generates a deterministic synthetic batch against a real `source_id` (`404` if missing) -- no file upload. Same audit action as the file-upload path. |
| `GET /sensor-ingestion/batches` | `OBSERVATION_READ` | Paginated, filterable by `source_id`. |
| `GET /sensor-ingestion/batches/{id}` | `OBSERVATION_READ` | `404` if not found or not in the caller's organization. |
| `GET /sensor-ingestion/batches/{id}/records` | `RAW_RECORD_READ` | Paginated, filterable by `validation_status`. Gated by the separate raw-record permission -- same split `docs/analytics/SOURCE_RELIABILITY.md` documents for `RawRecord` detail elsewhere in this codebase. |
| `POST /sensor-ingestion/batches/{id}/retry` | `OBSERVATION_INGEST` | `400` unless `job.status` is `failed` or `completed_with_errors`. Creates a brand-new `IngestionJob` row (the existing model, reused rather than a separate sensor-specific table -- `SensorIngestionJobResponse` is only the Pydantic response shape) with the same `job_type`; audit-logged (`sensor_ingestion.retry`) recording `retried_from_job_id`. |

## Sensor analytics (`app/api/routes/sensor_analytics.py`)

| Method & path | Permission | Notes |
|---|---|---|
| `GET /sensor-analytics/sensors/{id}/timeseries` | `OBSERVATION_READ` | Requires `measurement_type`; optional `since`/`until` (`400` via `QueryRangeTooLargeError`/`ValueError` if the range is invalid or too large); `max_points` (1-5000, default 500). Deterministically stride-sampled when the result exceeds `max_points`, or truncated (not averaged) when it exceeds `settings.SENSOR_MAX_RAW_SAMPLES` (1000) -- `aggregation_note` says which happened. |
| `GET /sensor-analytics/sensors/{id}/statistics` | `OBSERVATION_READ` | Same `measurement_type`/`since`/`until` validation as `timeseries`. Returns min/max/mean/median/stdev, percentiles, latest valid value, rate of change, and a `gap_summary` (gap count, max gap, "missing frame-like" flag); `insufficient_sample` flags a too-small window instead of returning misleading statistics. |
| `GET /sensor-analytics/sensors/{id}/health` | `SENSOR_READ` | Returns the four-signal `SensorHealthResponse` -- see `docs/analytics/SENSOR_HEALTH.md`. Read-only; no write to the sensor row. |
| `POST /sensor-analytics/sensors/{id}/health/recompute` | `SENSOR_MANAGE` | Computes health and may update `Sensor.lifecycle_status` from it (never for a sensor currently `maintenance`/`retired`); always an explicit, audited action (`sensor.lifecycle_status_recomputed`) -- see `docs/analytics/SENSOR_HEALTH.md`. |
| `POST /sensor-analytics/anomalies/run` | `OBSERVATION_INGEST` | Runs anomaly detection for one sensor/measurement_type; `404` if the sensor doesn't exist. Returns `created`/`already_known` anomaly lists plus `insufficient_baseline` -- never forces a judgment when there isn't enough history to detect against. |
| `GET /sensor-analytics/anomalies` | `ANOMALY_READ` | Paginated, filterable by `sensor_id`/`measurement_type`/`review_status`/`category`. |
| `GET /sensor-analytics/anomalies/{id}` | `ANOMALY_READ` | `404` if not found or not in the caller's organization. |
| `POST /sensor-analytics/anomalies/{id}/review` | `ANOMALY_REVIEW` | Records a human disposition (`review_status`, optional `review_note`); audit-logged (`anomaly.review`) with the new `review_status`. Never classifies an anomaly as a threat or fault itself -- see `docs/analytics/SENSOR_HEALTH.md`'s disclaimer-language section, which documents the identical discipline for anomaly counts surfaced through sensor health. |

## Cross-source comparison (`app/api/routes/cross_source_comparison.py`)

| Method & path | Permission | Notes |
|---|---|---|
| `POST /cross-source-comparison/compare` | `OBSERVATION_READ` | Read-only comparison of two observations (`404` if either is missing or belongs to another organization). See `docs/analytics/CROSS_SOURCE_COMPARISON.md`. |
| `POST /cross-source-comparison/links` | `RELATIONSHIP_MANAGE` | Re-runs the comparison, then persists it as an `EvidenceRelationship` (`relationship_type="cross_source_comparison"`, `origin="analyst_created"`), wrapping each observation as `Evidence` first. `201` with `EvidenceRelationshipResponse`. `400` via `IncomparableObservationsError` if the two observation IDs are identical. Audit-logged (`cross_source_comparison.link`) only when `create_comparison_link()`'s `created` flag is `True` -- a resubmission of an already-existing link is not double-audited. |

## Pagination

Every list endpoint above returns `{items, total, page, page_size}` via the same bounded
LIMIT/OFFSET `paginate()` helper (`app/api/pagination.py`) every other list endpoint in this
codebase uses -- `page_size` is clamped server-side to `settings.MAX_PAGE_SIZE` (200)
regardless of what a client requests, identical to `docs/api/TRACKING_API.md`'s pagination
section.

## Tenant isolation

Every route above resolves its sensor/batch/anomaly/observation through an org-scoped lookup
(`sensor_service.get_sensor()`, `sensor_ingestion_service.get_job()`,
`anomaly_service.get_anomaly()`, `observation_service.get_observation()`), each filtered by
`current_user.organization_id`. A request for a real row in another organization returns `404`,
never `403` -- the same discipline each layer's routes follow, chosen specifically so
a response never confirms whether a given ID exists outside the caller's own organization.

## Known gap: `SENSOR_QUALITY_REVIEW` is a dead permission

`Permission.SENSOR_QUALITY_REVIEW` (`"sensor_quality:review"`) is defined in
`app/core/security.py` and granted to both the `ANALYST` and `INVESTIGATOR` roles, alongside
`ANOMALY_READ`/`ANOMALY_REVIEW`, as part of this layer's permission additions. No route in the
codebase requires it: a repository-wide search for `SENSOR_QUALITY_REVIEW` turns up exactly
three matches, all inside `app/core/security.py` itself (the enum member and its two role-table
entries) -- zero usages in any `require_permission(...)` call anywhere under
`app/api/routes/`. The permission's own comment in `security.py` groups it with
`ANOMALY_REVIEW` as covering "a data-quality finding," but no such review endpoint exists yet;
the closest real thing is anomaly review (`POST /sensor-analytics/anomalies/{id}/review`),
which is gated by `ANOMALY_REVIEW` instead.

This is documented here honestly rather than silently: it is a genuine spec-vs-implementation
gap from this layer, not a security hole (nothing is under-protected -- a permission nobody
checks can only be more permissive than intended documentation would suggest, never less), and
not a route that was supposed to exist and got dropped from this list. If later work adds a
dedicated quality-finding-review endpoint separate from anomaly review, it should bind to this
already-provisioned permission rather than minting a new one; until then, treat
`SENSOR_QUALITY_REVIEW` as reserved but unused.
