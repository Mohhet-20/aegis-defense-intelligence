# Sensor Health (Section 10)

Status: implemented, live-verified, `app/services/sensor_health_service.py` at 97% test
coverage in the 507-test backend suite (92% overall).

Sensor health is computed **on demand** from a sensor's own stored rows -- the same
"no stale summary cache" principle `app/services/quality_service.py` already established
for data-platform-wide quality reporting. There is deliberately no background job writing a
health row on a schedule; every read either recomputes fresh (`GET
/sensor-analytics/sensors/{id}/health`) or explicitly asks the recomputed value to also be
applied to the sensor's lifecycle status (`POST
/sensor-analytics/sensors/{id}/health/recompute`).

## Four signals, never collapsed into one score

Section 10's explicit requirement, and the same discipline `docs/analytics/SOURCE_RELIABILITY.md`
documents for evidence concepts: these four fields are returned side by side on every
`SensorHealth`/`SensorHealthResponse`, and nothing in this codebase reduces them to a single
"health score."

| Signal | Dataclass | What it measures | Computed from |
|---|---|---|---|
| **Connectivity** | `ConnectivityHealth` | Is the sensor still reporting valid observations on roughly its expected cadence | `Sensor.last_seen_at` / `Sensor.last_ingestion_success_at` vs. `now`, compared against `Sensor.nominal_sampling_interval_seconds` (or `settings.SENSOR_HEARTBEAT_DEFAULT_SECONDS`, 3600s, if unset) |
| **Measurement quality** | `MeasurementQualityHealth` | Of the observations actually ingested in the last 7 days, how many parsed as invalid or carried a quality warning | `Observation.validation_status` counts, grouped, over a bounded 7-day window (`_QUALITY_WINDOW`) |
| **Anomaly status** | `AnomalyStatusHealth` | How many unreviewed statistical anomaly candidates exist for this sensor | `ObservationAnomaly` rows with `review_status == "unreviewed"` in the last 7 days, grouped by `severity` |
| **Device-reported status** | `DeviceReportedHealth` | What the sensor's own connector payload said about itself, verbatim | `Sensor.device_reported_status` / `_at` -- `None` unless a connector payload has ever explicitly supplied one |

`_connectivity()` resolves to one of `"never_connected"`, `"connected"`, `"missed_heartbeat"`,
or `"offline"`. `elapsed` (seconds since `last_seen_at`) is compared first against
`settings.SENSOR_OFFLINE_AFTER_SECONDS` (86400s) for `"offline"`, then against
`interval * settings.SENSOR_HEARTBEAT_MISSED_INTERVAL_MULTIPLE` (3.0x the nominal interval) for
`"missed_heartbeat"`; anything closer than that is `"connected"`. `_measurement_quality()`
marks `"degraded"` only when `invalid_rate > 0.2` or `warning_rate > 0.5` over the 7-day
window, and returns `"insufficient_data"` (not `"good"`) when there were zero observations to
assess -- the absence of data is never silently read as healthy.

### Confirmed live example

A real sensor in this deployment, queried via `GET /sensor-analytics/sensors/{id}/health`,
returned all four signals disagreeing with each other, which is exactly the point of keeping
them separate:

- **connectivity**: `"missed_heartbeat"` -- `elapsed` of 1671s exceeds 3.0x the nominal 60s
  sampling interval (180s threshold).
- **measurement_quality**: `"good"` -- 0 of 20 observations in the last 7 days were invalid; 1
  carried a quality warning.
- **anomaly_status**: `"4 unresolved"` -- 4 unreviewed anomaly candidates in the last 7 days.
- **device_reported**: `"(none)"` -- no connector payload for this sensor has ever supplied a
  device-reported status field.

A sensor can be missing its heartbeat while its actual measurements, when they do arrive, are
fine -- collapsing this into one score would have hidden that distinction and forced an
arbitrary judgment call about which signal "wins."

## The disclaimer-language discipline

Every explanation string in this module is written to stop a reader from over-interpreting a
statistical signal as a confirmed judgment. This is treated as a binding design rule, not
incidental wording, and the exact phrasings appear verbatim in the running UI:

- `_anomaly_status()`: *"N unreviewed anomaly candidate(s) in the last 7 days -- a statistical
  observation, not a confirmed threat or fault."*
- `_device_reported()`: *"verbatim status from the sensor's own connector payload -- never
  inferred."* The module docstring frames the whole file the same way: a connectivity gap or a
  reported fault is *"A statistical observation, never an automatic threat/hostility
  judgment."*
- `_connectivity()`'s `"never_connected"` case: *"no valid observation has ever been recorded
  for this sensor -- this is an absence of information, not a confirmed failure."*
- `_measurement_quality()`'s `"insufficient_data"` case: *"connectivity may be fine; there is
  simply nothing to assess quality on."*

None of the four signals, individually or combined, is ever surfaced as a hostility
determination, an equipment-fault confirmation, or anything else requiring human judgment --
they describe what the data shows and leave the interpretation to the analyst reading them.
This mirrors the rule `docs/analytics/SOURCE_RELIABILITY.md` already enforces for evidentiary
concepts: a statistical signal is never auto-converted into a truth claim.

## The datetime bug, and why it's worth documenting

`sensor_health_service.py` introduces an `_as_aware_utc()` helper -- the same fix pattern
already present as `_as_aware_utc` in `user_service.py` and under equivalent names in
`sensor_ingestion_service.py`/`anomaly_service.py`. SQLite round-trips a timezone-aware Python
`datetime` back as a naive one on read. `_connectivity()` subtracts `last_seen_at` (DB-read)
from `now` (freshly computed, aware) to get `elapsed`; before the fix this was a real
crash (`TypeError: can't subtract offset-naive and offset-aware datetimes`) the first time a
sensor had actually ingested an observation and the function hit that code path in tests.

The fix is applied in two places: inside `_connectivity()`, where both `sensor.last_seen_at`
and `sensor.last_ingestion_success_at` are normalized via `_as_aware_utc()` before either is
used in `elapsed = (now - last_seen_at).total_seconds()` or placed on the returned
`ConnectivityHealth`; and inside `_device_reported()`, where `as_of=_as_aware_utc(sensor.device_reported_status_at)`
gets the same treatment. The second site matters even though it does no arithmetic: without
it, `device_reported.as_of` would serialize without a `+00:00` UTC offset while
`connectivity.last_valid_observation_at` and `as_of` on the same `SensorHealthResponse` would
have one -- a genuine correctness inconsistency visible to an API client comparing two
timestamps on the same response, not merely an internal computation detail. It was caught by a
test assertion on the serialized response shape, not by a crash.

## Recompute vs. automatic computation

`GET /sensor-analytics/sensors/{id}/health` (`Permission.SENSOR_READ`) calls
`compute_health()` and returns the result -- read-only, no side effects, no write to the
sensor row.

`POST /sensor-analytics/sensors/{id}/health/recompute` (`Permission.SENSOR_MANAGE`) calls
`recompute_lifecycle_status()`, which computes health and then *may* update
`Sensor.lifecycle_status` based on it, following a fixed precedence: `"offline"` connectivity
wins outright, then `"never_connected"` maps to `"registered"`, then a `"degraded"`
measurement-quality status or any unresolved anomaly count maps to `"degraded"`, else
`"active"`. This is always an explicit, audited action (`audit_service.record()` with action
`"sensor.lifecycle_status_recomputed"`, capturing `previous_status`/`new_status`/`rule_version`)
-- it is never run implicitly on every `GET`, and `HEALTH_RULE_VERSION` ("1.0") is stamped on
every result so a future change to the recompute logic doesn't silently reinterpret history.

One override sits above all of this: if the sensor's current `lifecycle_status` is already
`"maintenance"` or `"retired"` (`SENSOR_LIFECYCLE_MANUAL_ONLY_TARGETS` in
`app/models/sensor.py`), `recompute_lifecycle_status()` still returns the freshly computed
`SensorHealth` but never overwrites the status -- those two states are manual-only
transitions an analyst enters and exits deliberately (`POST /sensors/{id}/lifecycle`, `POST
/sensors/{id}/retire`), and no automated health computation is allowed to move a sensor out of
them.

See also `docs/api/SENSOR_API.md` for the full route table, and
`docs/analytics/SOURCE_RELIABILITY.md` for the parallel discipline this layer follows for
evidentiary (rather than operational) concepts.
