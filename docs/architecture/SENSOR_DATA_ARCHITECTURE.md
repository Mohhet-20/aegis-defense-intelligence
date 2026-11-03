# Sensor Data Architecture (Phase 6)

**Status: REAL.** This supersedes `docs/architecture/MULTISENSOR_CONTRACTS.md`'s
"planned" section for Phase 6 -- sensor health, observation-quality scoring,
timestamp normalization, and anomaly detection are all implemented, migrated
(`e416c9a24fa4`), and covered by the backend test suite (507 passed, 92%
overall coverage; `app/sensors/quality.py` 98%, `app/sensors/units.py` 100%,
`app/sensors/statistics.py` 99%, `app/services/sensor_ingestion_service.py`
89%, `app/services/sensor_service.py` 92%). `MULTISENSOR_CONTRACTS.md` is left
in place as the historical planning record, not deleted -- its Phase 3
(fusion/correlation) section is still planned and unaffected by this phase.

## What's reused from Phase 1, unchanged in meaning

- `Sensor` (`app/models/sensor.py`) and `Observation` (`app/models/observation.py`)
  -- both tables already existed. Phase 6 extends them with new nullable (or
  server-defaulted) columns rather than replacing them; no Phase 1 column is
  repurposed or dropped. `Sensor.status` (`active`/`inactive`/`fault`/`unknown`)
  keeps its exact Phase 1 meaning -- it is a separate field from the new
  `lifecycle_status` below, not superseded by it.
- `IngestionJob` and `RawRecord` (`app/models/ingestion_job.py`,
  `app/models/raw_record.py`), both introduced in Phase 2 for Event ingestion.
  Sensor batches reuse these same tables rather than a competing
  `SensorIngestionJob`/`SensorRawRecord` pair -- `IngestionJob.job_type` simply
  gets three new values (`sensor_json_batch`, `sensor_csv_batch`,
  `sensor_synthetic`), and `RawRecord.event_id` just stays `NULL` for every row
  a sensor batch produces. See `docs/data/CANONICAL_SENSOR_OBSERVATION.md` for
  how a `RawRecord` relates to the `Observation` it may produce.
- The registry CRUD + audit-trail pattern Phase 1/Phase 3 already
  established: `GET/POST /sensors`, `GET/PATCH /sensors/{id}` were real before
  this phase; Phase 6 adds the lifecycle and status-history routes on top
  (see `docs/data/SENSOR_REGISTRY.md`).

## What's new

- **`app/sensors/` package** -- pure, DB-free computation modules: `quality.py`
  (per-record validation/classification), `units.py` (closed-table unit
  conversion), `statistics.py` (descriptive time-series statistics),
  `anomaly.py` (heuristic anomaly candidates). None of these import SQLAlchemy;
  every caller supplies whatever history/context a check needs, keeping each
  module independently unit-testable (the 98-100% coverage above reflects
  this).
- **`app/sensors/adapters/`** -- `SyntheticSensorConnector`,
  `SensorCsvBatchConnector`, `SensorJsonBatchConnector`, behind a closed
  allow-list registry (`app/sensors/adapters/registry.py`). See "Adapter
  registry pattern" below.
- **`observation_anomalies` table** (`app/models/observation_anomaly.py`) --
  the one genuinely new table this phase adds. Everything else is a column
  addition to an existing table. See `docs/data/CANONICAL_SENSOR_OBSERVATION.md`.
- **Services**: `app/services/sensor_ingestion_service.py` (batch ingestion
  orchestration), `app/services/sensor_health_service.py` (on-demand health
  computation + lifecycle recompute), `app/services/anomaly_service.py`
  (anomaly orchestration + review workflow), `app/services/timeseries_service.py`
  (bounded time-series queries over `app/sensors/statistics.py`).
- **Routes**: `app/api/routes/sensors.py` (registry + lifecycle),
  `app/api/routes/sensor_ingestion.py` (batch submission/retry/inspection),
  `app/api/routes/sensor_analytics.py` (time series, statistics, health,
  anomalies).

## Adapter registry pattern (reused discipline, new registry)

`app/sensors/adapters/registry.py` is a **separate** closed allow-list from
`app.connectors.registry` (the Event-ingestion one) and from the CV model
registry and tracker registry before it -- same discipline, deliberately not
the same table, because a sensor observation batch and an Event batch are
different record shapes even when both arrive as JSON or CSV. `format` on
`POST /sensor-ingestion/batches` is a key into `SENSOR_BATCH_FORMATS = ("json",
"csv")`; the synthetic connector is reached by a separate `adapter_key`
(`sensor_synthetic`), never by a client-supplied dynamic import. No HTTP
sensor connector is registered yet -- Section 5's "do not add unrestricted
network access" means wiring one up (reusing
`app.connectors.http_connector.HttpApiConnector`'s existing SSRF-hardened
fetch path) is deferred, not attempted here.

## Execution model (stated honestly)

A sensor batch (`submit_file_batch()` / `submit_synthetic_batch()` in
`sensor_ingestion_service.py`) runs **synchronously inside the API request**
that submits it -- exactly the same execution model `IngestionJob`,
`FusionJob`, `InferenceJob`, and `TrackingJob` already use. There is still no
background worker or queue anywhere in this codebase. Anomaly checks
(`POST /sensor-analytics/anomalies/run`) and health recompute
(`POST /sensor-analytics/sensors/{id}/health/recompute`) are likewise
synchronous, on-demand calls -- never a scheduled job, because there is no
scheduler in this codebase to run one on.

## Data flow, end to end

```
Sensor batch (file upload or synthetic config)
        |
        v
app/sensors/adapters/{synthetic,csv_batch,json_batch}.py  (parse -> RawRecord candidates)
        |
        v
sensor_ingestion_service._process_batch()
        |
        +--> RawRecord  (ALWAYS written -- accepted, rejected, or duplicate)
        |
        +--> app/sensors/quality.evaluate_observation()  (validate + classify)
        |         |
        |         v
        +--> Observation  (written ONLY if quality_lib says is_accepted)
                  |
                  +--> sensor.lifecycle_status: registered/offline -> active
                  +--> sensor.last_seen_at / last_ingestion_success_at updated

(separately, on demand)
app/services/timeseries_service.py  -> app/sensors/statistics.py        -> DescriptiveStatistics
app/services/anomaly_service.py     -> app/sensors/anomaly.py            -> ObservationAnomaly
app/services/sensor_health_service.py -> compute_health() / recompute_lifecycle_status()
```

Every `Observation` an ingestion batch creates carries `source_record_id`
(the `RawRecord` it was normalized from) and `ingestion_job_id` -- an analyst
can always trace one canonical observation back to the exact raw payload and
batch that produced it, the same lineage discipline `TrackObservation` /
`DetectionResult` established in Phase 4/5.

## Health is never cached

`sensor_health_service.compute_health()` recomputes all four health signals
(connectivity, measurement quality, anomaly status, device-reported status)
fresh from the sensor's own `Observation`/`ObservationAnomaly` rows on every
call -- the same "no stale summary" principle `app/services/quality_service.py`
already established data-platform-wide. `Sensor.lifecycle_status` is the one
piece of computed health that IS persisted, and only ever changes through an
explicit call: either an analyst's own lifecycle transition
(`sensor_service.transition_lifecycle_status()`) or an explicit
`recompute_lifecycle_status()` call (`POST /sensors/{id}/health/recompute`),
never silently on every read. See `docs/data/SENSOR_REGISTRY.md` for the
exact transition rules.

## What Phase 6 deliberately does NOT build

- A background worker or job queue of any kind (see "Execution model" above).
- An HTTP/network sensor connector (deferred, see "Adapter registry pattern").
- Cross-sensor correlation/fusion -- an anomaly candidate is scoped to exactly
  one sensor + measurement type; recognizing that two different sensors'
  observations describe the same real-world event is still Phase 3
  (`MULTISENSOR_CONTRACTS.md`'s "Cross-source association"), unimplemented.
- Any machine-learning anomaly model -- `app/sensors/anomaly.py` is entirely
  documented statistical heuristics (range/z-score/MAD/rate-of-change/
  heartbeat/repeated-value/sampling-gap), never an unsupported ML claim.
- A threat/hostility classification of any kind. `ANOMALY_SEVERITIES` is a
  data-quality severity scale (`info`/`low`/`medium`/`high`) with no
  "critical"/threat-sounding term, and `ObservationAnomaly.category` never
  becomes anything resembling a threat label.
- A per-sensor calibration coefficient that wasn't supplied by the source --
  `app/sensors/units.py` performs only standard, documented unit-system
  conversions; it has no mechanism to invent a sensor-specific correction.

## Known spec-vs-implementation gap

`Permission.SENSOR_QUALITY_REVIEW` exists in `app/core/security.py` and is
granted to both `ANALYST` and `INVESTIGATOR`, but no route in this codebase
currently requires it -- anomaly review actually runs under `ANOMALY_REVIEW`
(`POST /sensor-analytics/anomalies/{id}/review`). This is disclosed rather
than hidden; see the permission table in `docs/data/SENSOR_REGISTRY.md`.
