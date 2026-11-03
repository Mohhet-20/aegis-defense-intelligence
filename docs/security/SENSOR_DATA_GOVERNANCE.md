# Sensor Data Governance (Phase 6)

Status: implemented, live-verified, backend suite 507 passed / 92% overall coverage; permission
enforcement and tenant isolation confirmed by `tests/test_sensor_registry_api.py`,
`tests/test_sensor_ingestion_api.py`, `tests/test_sensor_analytics_api.py`, and
`tests/test_cross_source_comparison_api.py`.

## Explicit prohibitions, enforced in code, not just policy

- **No autonomous targeting or weapon-control logic.** This remains a decision-support platform
  end to end -- nothing in `app/sensors/`, `app/services/sensor_ingestion_service.py`,
  `app/services/anomaly_service.py`, or `app/services/sensor_health_service.py` ever issues a
  command to any external system.
- **No automatic threat/hostility judgment.** `app/sensors/anomaly.py`'s module docstring states
  this directly: every detection method is "a documented STATISTICAL heuristic over a sensor's
  own recent history -- never an unsupported machine-learning claim, and NEVER a
  threat/hostility judgment." `ANOMALY_SEVERITIES` is a data-quality severity scale
  (`info`/`low`/`medium`/`high`) with no "critical" or threat-sounding term, and
  `AnomalyCandidate.severity`/`ObservationAnomaly.category` are closed, enumerated values
  containing no threat label. `sensor_health_service.py` carries the identical discipline: its
  anomaly-status explanation string is phrased verbatim as "a statistical observation, not a
  confirmed threat or fault," and no sensor-health signal, individually or combined, is ever
  surfaced as a hostility determination -- see `docs/analytics/SENSOR_HEALTH.md`'s "disclaimer-
  language discipline" section for the full set of phrasings this phase treats as a binding
  design rule, not incidental wording.
- **No cross-sensor correlation or fusion.** An `ObservationAnomaly` is scoped to exactly one
  `(sensor_id, measurement_type)` pair; recognizing that two different sensors' observations
  describe the same real-world event is still Phase 3 (`docs/architecture/MULTISENSOR_CONTRACTS.md`'s
  "Cross-source association"), unimplemented. `POST /cross-source-comparison/compare` and
  `POST /cross-source-comparison/links` compare exactly two already-identified observations an
  analyst supplies -- they never search for or infer a match on their own.

## Authorization matrix

| Permission | Analyst | Investigator | Viewer | Administrator |
|---|---|---|---|---|
| `SENSOR_MANAGE` (create/update a sensor, lifecycle transitions, retire, health recompute) | yes | no | no | yes |
| `SENSOR_READ` (read sensors, status history, health) | yes | yes | yes | yes |
| `OBSERVATION_READ` (read observations, time series, statistics) | yes | yes | yes | yes |
| `OBSERVATION_INGEST` (submit/retry a sensor batch, run anomaly checks) | yes | no | no | yes |
| `RAW_RECORD_READ` (inspect pre-validation raw records) | yes | yes | no | yes |
| `ANOMALY_READ` (list/read anomaly candidates) | yes | yes | yes | yes |
| `ANOMALY_REVIEW` (disposition an anomaly candidate) | yes | yes | no | yes |
| `SENSOR_QUALITY_REVIEW` | yes | yes | no | yes |
| `RELATIONSHIP_MANAGE` (create a cross-source comparison link) | yes | yes | no | yes |

This mirrors the exact "can look, can flag, cannot spend compute/cannot change the registry"
boundary Phase 4/5 already drew for `INFERENCE_RUN`/`TRACKING_RUN`: Investigator can review and
annotate anomalies but cannot submit new batches or manage the sensor registry, even though it
can read everything Analyst can. Every route decides this server-side via `require_permission`
(`app/core/security.py`) -- confirmed per-route in `app/api/routes/sensors.py`,
`app/api/routes/sensor_ingestion.py`, `app/api/routes/sensor_analytics.py`, and
`app/api/routes/cross_source_comparison.py`.

## A defined-but-unenforced permission, disclosed honestly

`Permission.SENSOR_QUALITY_REVIEW` (`"sensor_quality:review"`) exists in `app/core/security.py`
and is granted to both `ANALYST` and `INVESTIGATOR` in `ROLE_PERMISSIONS`, but
`grep -rn "SENSOR_QUALITY_REVIEW" backend/app/` finds zero usages outside its own enum and
role-table definitions -- **no route in this codebase requires it**. Anomaly review actually
runs under `ANOMALY_REVIEW` (`POST /sensor-analytics/anomalies/{id}/review`), and there is no
separate data-quality-finding review workflow for this permission to gate. This is a real,
honestly-documented spec-vs-implementation gap, not a security hole: nothing dangerous is
exposed by the permission sitting unused, since no code path checks it at all. It is tracked
here and in `docs/architecture/SENSOR_DATA_ARCHITECTURE.md`'s "Known spec-vs-implementation gap"
section rather than silently dropped from the role table or quietly wired to an arbitrary route
to make it "used."

## Tenant isolation

Every sensor/observation/anomaly query filters by `organization_id`: `sensor_service.get_sensor()`,
`observation_service.get_observation()`, `sensor_ingestion_service.get_job()`,
`anomaly_service.get_anomaly()`, and every `*_query()` builder all take `organization_id` as a
required argument, the same `OrgScopedMixin` discipline every prior phase's tables follow. A
request for another organization's sensor, observation, ingestion job, or anomaly returns
**`404`, never `403`** -- the same "don't even confirm it exists" rule every other resource in
this codebase follows, so a cross-tenant probe cannot distinguish "not yours" from "doesn't
exist." `tests/test_sensor_registry_api.py`, `tests/test_sensor_ingestion_api.py`, and
`tests/test_sensor_analytics_api.py` each include a cross-tenant-access assertion confirming
this at the HTTP layer.

## Input validation

- `format` on `POST /sensor-ingestion/batches` is checked against the literal `("json", "csv")`
  tuple before any adapter is touched; an unsupported value is `400`.
- A sensor batch's `adapter_key`/connector is only ever resolved through the closed
  `app/sensors/adapters/registry.py` allow-list -- never a dynamic import of a client-supplied
  string, the same discipline `app.connectors.registry` and the CV/tracker registries already
  established.
- `SyntheticSensorConnector.validate_config()` rejects a missing `sensor_id`/`measurement_type`
  or a `count` outside `1..2000` before any record is generated; the resulting job is persisted
  as `status="failed"` with the config error recorded, never silently ignored.
- A batch exceeding `settings.MAX_UPLOAD_BYTES` (5 MB) is rejected (`413`) before the content is
  decoded at all.
- An unknown `sensor_id` or a batch submitted against a `retired` sensor is rejected per-record
  (`unknown_sensor`/`sensor_retired` quality flags), never silently mapped to a different sensor
  or accepted anyway.

## Non-destructive history and audit

Every state-changing sensor/observation/anomaly action is recorded via the existing
`audit_service.record()` mechanism, unchanged from prior phases: `sensor.create`,
`sensor.update`, `sensor.lifecycle_status_recomputed`, `sensor_ingestion.run`,
`sensor_ingestion.retry`, `anomaly.review`, and `cross_source_comparison.link` all capture the
acting user, organization, target type/id, outcome, and relevant context metadata. This is
queryable via the existing `/audit` endpoint and is also surfaced directly on
`GET /sensors/{id}/status-history`. A `RawRecord` and an `Observation` are never edited after
creation -- a retry creates a new `IngestionJob` (and new `RawRecord`/`Observation` rows), never
a rewrite of the original failed attempt's rows, so an operator can always see exactly what the
first attempt actually produced.

## Data provenance: synthetic-only demo data

All demo/seed sensor data is synthetic, clearly generated via `SyntheticSensorConnector` with a
fixed seed, and is never presented as real sensor telemetry. Every synthetic record carries
`data_origin="synthetic_demo"` on its `Observation` row and an explicit
`"note": "deterministic synthetic demonstration record -- not a real sensor reading"` field in
its own payload -- the same synthetic-fixture-provenance discipline this codebase already
applies to the CV/tracking demo fixtures (`app/tracking/synthetic_fixture.py`). A caller or
reviewer inspecting either the `Observation` or the originating `RawRecord` can tell at a glance
that the data did not come from a live sensor.
