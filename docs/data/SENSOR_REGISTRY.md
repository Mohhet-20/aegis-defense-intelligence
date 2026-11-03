# Sensor Registry (Phase 6)

**Status: REAL.** Phase 1's `Sensor` table plus the Phase 6 (Section 3)
registry metadata and lifecycle state machine migrated in `e416c9a24fa4`.
This supersedes `docs/architecture/MULTISENSOR_CONTRACTS.md`'s description of
`Sensor` as identity/type/status/`last_seen_at` only -- the richer
category/manufacturer/measurement-configuration/lifecycle fields below are
now real columns with real routes exercising them.

## Fields (`app/models/sensor.py`)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID string | generated |
| `organization_id` | string | required, FK |
| `source_id` | string, nullable | FK `data_sources.id`, `ON DELETE SET NULL` |
| `name` | string | required |
| `sensor_type` | string | free-text subtype (e.g. `"camera"`, `"gps"`, `"environmental"`) -- Phase 1 field, unchanged meaning |
| `status` | string | Phase 1's simple connectivity flag: `active`/`inactive`/`fault`/`unknown` (`SENSOR_STATUSES`). Kept exactly as-is -- a separate field from `lifecycle_status`, never collapsed into it. |
| `last_seen_at` | datetime, nullable | Phase 1 field |
| `config_version` | string, nullable | Phase 1 field |
| `capability_metadata` | JSON dict | Phase 1 field |
| `category` | string, nullable | **Phase 6.** Broad grouping distinct from `sensor_type`; `NULL` until an analyst sets one, never backfilled with a guess |
| `description` | string, nullable | **Phase 6.** |
| `manufacturer` | string, nullable | **Phase 6.** |
| `model_name` | string, nullable | **Phase 6.** |
| `asset_id` | string, nullable | **Phase 6.** FK `assets.id`, `ON DELETE SET NULL` |
| `measurement_types` | JSON list | **Phase 6.** Measurement types this sensor is authorized/expected to report, e.g. `["temperature_c", "battery_voltage"]`. Empty means "not yet configured" -- quality/analytics treat an unconfigured type as "no validation rule exists," never an automatic rejection. |
| `measurement_units` | JSON dict | **Phase 6.** `measurement_type -> unit string`, e.g. `{"temperature_c": "celsius"}` |
| `operating_range` | JSON dict | **Phase 6.** `measurement_type -> {"min": float, "max": float}`; only checked when both bounds are present |
| `nominal_sampling_interval_seconds` | float, nullable | **Phase 6.** Drives heartbeat/sampling-gap checks |
| `expected_data_format` | string, nullable | **Phase 6.** |
| `sensor_timezone` | string | **Phase 6.** Default `"UTC"` |
| `lifecycle_status` | string | **Phase 6.** One of `SENSOR_LIFECYCLE_STATUSES`, default `"registered"` -- see "Lifecycle state machine" below |
| `last_ingestion_success_at` | datetime, nullable | **Phase 6.** |
| `device_reported_status` | string, nullable | **Phase 6.** Populated ONLY when an ingested record's payload explicitly carries a `device_status` field -- never inferred from connectivity or quality |
| `device_reported_status_at` | datetime, nullable | **Phase 6.** |
| `retired_at` | datetime, nullable | **Phase 6.** |
| `retired_by_user_id` | string, nullable | **Phase 6.** FK `users.id`, `ON DELETE SET NULL` |

The model itself still stores identity/configuration, not computed health --
health is always derived on demand from the sensor's own `Observation`/
`ObservationAnomaly` rows by `app/services/sensor_health_service.py`, never
cached on `Sensor`. The one exception is `lifecycle_status`, which IS a
persisted field, but only changes through the explicit paths below.

## Lifecycle state machine (`SENSOR_LIFECYCLE_STATUSES`)

`registered`, `active`, `degraded`, `offline`, `maintenance`, `retired`.

| Transition | Trigger | Where |
|---|---|---|
| `registered -> active` | the first valid observation is ingested | automatic, inside `sensor_ingestion_service._process_batch()`, the moment `outcome.is_accepted` is true and `sensor.lifecycle_status in ("registered", "offline")` |
| `offline -> active` | a new valid observation arrives | automatic, same code path as above |
| `active -> degraded` | measurement-quality or unresolved-anomaly signal crosses a threshold while observations are still arriving | computed by `sensor_health_service.recompute_lifecycle_status()` |
| `active -> offline` | no valid observation within the heartbeat window | computed by `recompute_lifecycle_status()` |
| `degraded -> active` | quality/anomaly signal recovers | computed by `recompute_lifecycle_status()` |
| `degraded -> offline` | heartbeat window also elapses | computed by `recompute_lifecycle_status()` |
| `* -> maintenance` | explicit analyst action only, never inferred from data | `sensor_service.transition_lifecycle_status()` |
| `maintenance -> active` | explicit analyst action only | `sensor_service.transition_lifecycle_status()` |
| `* -> retired` | explicit analyst action only; terminal | `sensor_service.retire_sensor()` (thin wrapper over `transition_lifecycle_status()`) |

`recompute_lifecycle_status()` is **never run implicitly on every read** --
it only runs when `POST /sensors/{sensor_id}/health/recompute` is called, and
it explicitly refuses to override a sensor currently in `maintenance` or
`retired` (`SENSOR_LIFECYCLE_MANUAL_ONLY_TARGETS`), consulting
`compute_health()`'s four signals:

- `connectivity.status == "offline"` -> `offline`
- `connectivity.status == "never_connected"` -> `registered`
- `measurement_quality.status == "degraded"` or `anomaly_status.unresolved_count > 0` -> `degraded`
- otherwise -> `active`

A change is written and audited (`sensor.lifecycle_status_recomputed`) only
if the computed status actually differs from the current one -- a no-op
recompute writes nothing.

`sensor_service.transition_lifecycle_status()` separately enforces its own
analyst-initiated transition table (`_ANALYST_ALLOWED_TRANSITIONS`), which is
intentionally broader than the automatic rules above -- an analyst can move a
sensor directly from `degraded`/`offline` back to `active` by hand (e.g.
after a confirmed physical fix) without waiting for the next recompute, and
can always reach `maintenance`/`retired` from any non-terminal state.
`retired` is terminal and irreversible through this function
(`_ANALYST_ALLOWED_TRANSITIONS["retired"] = set()`); a retired sensor also
accepts no further observation batches
(`sensor_ingestion_service._process_batch()` rejects with
`sensor_retired`/invalid), but its historical `Observation` data remains
fully queryable.

## Registry routes (`app/api/routes/sensors.py`)

| Route | Permission | Notes |
|---|---|---|
| `GET /sensors` | `SENSOR_READ` | filters: `category`, `lifecycle_status`, `sensor_type`, `measurement_type`, `search` (name/description) |
| `POST /sensors` | `SENSOR_MANAGE` | creates with `status="unknown"`, `lifecycle_status="registered"` |
| `GET /sensors/{sensor_id}` | `SENSOR_READ` | |
| `PATCH /sensors/{sensor_id}` | `SENSOR_MANAGE` | partial update; `status` is validated against `SENSOR_STATUSES` |
| `GET /sensors/{sensor_id}/status-history` | `SENSOR_READ` | returns `AuditRecord` rows for this sensor -- see "Audit trail" below |
| `POST /sensors/{sensor_id}/lifecycle` | `SENSOR_MANAGE` | body: `{new_status, note}`; 400 on an invalid transition |
| `POST /sensors/{sensor_id}/retire` | `SENSOR_MANAGE` | thin wrapper over the lifecycle route targeting `retired` |

Analytics routes (`app/api/routes/sensor_analytics.py`) that act on a sensor:

| Route | Permission |
|---|---|
| `GET /sensor-analytics/sensors/{sensor_id}/timeseries` | `OBSERVATION_READ` |
| `GET /sensor-analytics/sensors/{sensor_id}/statistics` | `OBSERVATION_READ` |
| `GET /sensor-analytics/sensors/{sensor_id}/health` | `SENSOR_READ` |
| `POST /sensor-analytics/sensors/{sensor_id}/health/recompute` | `SENSOR_MANAGE` |
| `POST /sensor-analytics/anomalies/run` | `OBSERVATION_INGEST` |
| `GET /sensor-analytics/anomalies`, `GET /sensor-analytics/anomalies/{id}` | `ANOMALY_READ` |
| `POST /sensor-analytics/anomalies/{id}/review` | `ANOMALY_REVIEW` |

Every route decides permission server-side via `require_permission` --
never a frontend-only check. `Analyst` holds the full set above (including
`SENSOR_MANAGE` and `OBSERVATION_INGEST`); `Investigator` holds the read/
review half (`SENSOR_READ`, `OBSERVATION_READ`, `ANOMALY_READ`,
`ANOMALY_REVIEW`) but not `SENSOR_MANAGE` or `OBSERVATION_INGEST`; `Viewer`
holds only `SENSOR_READ`, `OBSERVATION_READ`, `ANOMALY_READ`.

**Known gap:** `Permission.SENSOR_QUALITY_REVIEW` is defined in
`app/core/security.py` and granted to both `Analyst` and `Investigator`, but
no route in this codebase requires it -- the anomaly-review route above
actually gates on `ANOMALY_REVIEW`. This is a real spec-vs-implementation
gap (confirmed via grep: zero usages of `SENSOR_QUALITY_REVIEW` outside the
enum/role-table definitions), disclosed here rather than hidden.

## Status-history / audit trail

There is no separate per-sensor history table. `GET /sensors/{id}/status-history`
and `sensor_service.get_status_history()` both reuse the append-only
`AuditRecord` trail (`audit_service.list_for_target(target_type="sensor",
target_id=sensor_id)`) -- the same choice Phase 3 already made for
relationship/conflict/assessment review history. Three actions are recorded
against a sensor: `sensor.create`, `sensor.update` (from the registry
routes), `sensor.lifecycle_transition` (an analyst's explicit transition,
with `previous_status`/`new_status`/`note` in `context_metadata`), and
`sensor.lifecycle_status_recomputed` (an automatic recompute that actually
changed the status, with `previous_status`/`new_status`/`rule_version`).

## What this does NOT do

- `lifecycle_status` is never recomputed implicitly on a plain `GET` --
  only an explicit `POST .../health/recompute` call, or an ingested
  observation's `registered`/`offline -> active` bump, ever changes it.
- A `retired` sensor can never be un-retired through
  `transition_lifecycle_status()` -- there is no code path back out.
- No lifecycle transition is ever inferred for `maintenance`/`retired`; both
  are always an explicit, audited analyst action with an `actor_user_id`.
