# Anomaly Detection (Section 9)

## Status

Implemented and tested: `app/sensors/anomaly.py` (89% coverage,
`tests/test_sensor_statistics_and_anomaly.py`) and its orchestrator
`app/services/anomaly_service.py` (96% coverage, `tests/test_anomaly_service.py`), persisted as
`ObservationAnomaly` rows (`app/models/observation_anomaly.py`) and exposed via
`POST /sensor-analytics/anomalies/run` (`Permission.OBSERVATION_INGEST`),
`GET /sensor-analytics/anomalies` and `GET /sensor-analytics/anomalies/{id}`
(`Permission.ANOMALY_READ`), and `POST /sensor-analytics/anomalies/{id}/review`
(`Permission.ANOMALY_REVIEW`) in `app/api/routes/sensor_analytics.py`. Live-verified against a
seeded synthetic outlier.

Every method in `app/sensors/anomaly.py` is a documented **statistical heuristic** over a
sensor's own recent history -- never an unsupported machine-learning claim, and never a
threat/hostility judgment. A result is a candidate for an analyst to interpret, not a conclusion:
`ANOMALY_SEVERITIES` is `("info", "low", "medium", "high")`, deliberately excluding any
"critical"/"threat"-sounding term (Section 9: "do not label anomalies as threats"). All functions
are pure -- `anomaly_service.py` supplies the already-fetched recent history and persists
whichever candidates these functions actually return.

## The detection methods

`ANOMALY_DETECTION_METHODS` names seven methods; `anomaly_service.run_checks()` runs the first
six against the latest observation whenever any history exists, plus `missing_heartbeat`
unconditionally:

| Method | Category | Trigger | Settings |
|---|---|---|---|
| `range_violation` | `statistical_deviation` | value below/above the sensor's configured `operating_range` for this measurement type | (range comes from `Sensor.operating_range`, not a global setting) |
| `rolling_zscore` | `statistical_deviation` | `\|z\| >= SENSOR_ANOMALY_ZSCORE_THRESHOLD` against the mean/stdev of the last `SENSOR_ANOMALY_ROLLING_WINDOW` prior values | `SENSOR_ANOMALY_MIN_BASELINE_SAMPLES=8`, `SENSOR_ANOMALY_ROLLING_WINDOW=10`, `SENSOR_ANOMALY_ZSCORE_THRESHOLD=3.0` |
| `median_absolute_deviation` | `statistical_deviation` | robust z-score `0.6745 * (value - median) / MAD >= SENSOR_ANOMALY_MAD_THRESHOLD` | `SENSOR_ANOMALY_MIN_BASELINE_SAMPLES=8`, `SENSOR_ANOMALY_MAD_THRESHOLD=3.5` |
| `rate_of_change` | `statistical_deviation` | the rate between the latest two points is `>= SENSOR_ANOMALY_ZSCORE_THRESHOLD` standard deviations from the mean of recent rates | `SENSOR_ANOMALY_MIN_BASELINE_SAMPLES=8` prior *rate* samples required (so effectively needs more raw history than the other two) |
| `missing_heartbeat` | `sensor_health` | no valid observation ever, or elapsed time since the last valid one exceeds `nominal_sampling_interval_seconds * SENSOR_HEARTBEAT_MISSED_INTERVAL_MULTIPLE` (falling back to `SENSOR_HEARTBEAT_DEFAULT_SECONDS` when the sensor has no configured interval) | `SENSOR_HEARTBEAT_MISSED_INTERVAL_MULTIPLE=3.0`, `SENSOR_HEARTBEAT_DEFAULT_SECONDS=3600.0` |
| `repeated_value` | `data_quality` | identical run length at or above `SENSOR_MAX_IDENTICAL_RUN`, reusing `app/sensors/quality.py`'s `check_repeated_value` | `SENSOR_MAX_IDENTICAL_RUN=5` |
| `sampling_gap` | `data_quality` | gap since the prior observation exceeds `nominal_interval_seconds * missed_multiple`, reusing `check_sampling_gap` | `SENSOR_HEARTBEAT_MISSED_INTERVAL_MULTIPLE=3.0` |

`rolling_zscore` and `median_absolute_deviation` and `rate_of_change` all report
`insufficient_baseline=True` with an explanatory `reason` (e.g. `"only 3 prior samples
available; 8 required for a rolling z-score baseline"`) rather than manufacturing a baseline from
too little history -- `run_checks()` surfaces these under its `insufficient_baseline` dict keyed
by reason, every time a method could not run at all (Section 9: "report that limitation rather
than manufacturing a baseline"). A baseline with zero variance (`rolling_zscore`/`rate_of_change`)
or zero median absolute deviation (`median_absolute_deviation`) is likewise reported as
undefined, never divided-by-zero into a crash or a fabricated score.

`range_violation`, `rolling_zscore`, `median_absolute_deviation`, and `rate_of_change` are
point-based (anchored to one `observation_id`); `missing_heartbeat` and `sampling_gap` are
window-based (`observation_id` is `NULL`, anchored only to `window_start`/`window_end`) because
neither has one single triggering row -- a missing heartbeat is, definitionally, the *absence*
of a row.

## Severity

`rolling_zscore` and `median_absolute_deviation` both escalate to `"high"` once the deviation
reaches 1.5x their own threshold (e.g. `abs(z) >= threshold * 1.5`), otherwise `"medium"`.
`range_violation`, `rate_of_change`, and `missing_heartbeat` are always `"medium"`.
`repeated_value` and `sampling_gap` are always `"low"`. `"info"` exists in `ANOMALY_SEVERITIES`
but no current detection method assigns it.

## `category` vs. `review_status`: automatic detection, never automatic judgment

Section 9 requires these stay separate, and the code enforces it structurally, not just by
convention. `ObservationAnomaly.category` is one of `ANOMALY_CATEGORIES` --
`statistical_deviation`, `data_quality`, `sensor_health`, or `analyst_confirmed` -- and every
detection method above sets it to one of the first three *automatically*, the moment a candidate
is computed. `analyst_confirmed` is never set by a detection method; it is one of two outcomes of
`anomaly_service.review_anomaly()`'s `_REVIEW_STATUS_CATEGORY` mapping
(`confirmed_unusual -> analyst_confirmed`, `data_quality_issue -> data_quality`), which only runs
when an analyst calls `POST /sensor-analytics/anomalies/{id}/review`.

`review_status` (`ANOMALY_REVIEW_STATUSES`: `unreviewed`, `confirmed_unusual`,
`data_quality_issue`, `expected_known_context`, `unresolved`) starts at `unreviewed` for every
newly persisted anomaly and is changed to anything else **only** through that same explicit
review action -- never computed automatically by any detection method or background process.
Reviewing an anomaly corrects an analyst's interpretation of it, not the underlying measurement:
the originating `Observation` row is never rewritten, mirroring the review-field pattern already
established by `RiskAssessment` and `EvidenceRelationship`.

`run_checks()` is idempotent per `(observation_id, detection_method)` pair -- re-running checks
against an unchanged series never creates a duplicate row (`_existing_candidate` short-circuits
persistence and the result is returned under `already_known` instead of `created`).
`missing_heartbeat` candidates are deduplicated differently since they have no `observation_id`:
a new one is only persisted if no existing `unreviewed` `missing_heartbeat` row already exists
for that sensor/measurement_type.

## Real seeded examples

`scripts/seed.py` seeds an environmental sensor (`temperature_c`, `operating_range.max = 45.0`)
with a 20-point synthetic series (`base_value=22.0`) and one deliberate synthetic outlier
(`value_overrides={"19": 61.0}`) -- a single point pushed well outside the configured range, so
the anomalies below are genuine detections against a real synthetic series, not staged rows.
Confirmed live against that seed, across all four point-based `statistical_deviation` methods:

- **`rate_of_change`**, severity `medium`.
- **`median_absolute_deviation`**, severity `high` -- `"value 61.0 has a robust z-score of 54.13
  against the median ... (MAD-based threshold 3.5)"`.
- **`rolling_zscore`**, severity `high` -- `"value 61.0 is 59.74 standard deviations from the
  rolling mean ... (threshold 3.0)"`.
- **`range_violation`**, severity `medium` -- `"value 61.0 is above the configured maximum
  45.0"`.

All four fired from the same single injected point, which is expected: each method is an
independent lens on the same data, not a vote toward one combined score -- Section 9 never asks
for or implies a single collapsed anomaly score.

## A datetime bug that affects missed-heartbeat and time-window correctness

SQLite has no real "timestamp with timezone" type: a SQLAlchemy `DateTime(timezone=True)` column
still round-trips a **naive** datetime through it, while a freshly created Python
`datetime.now(timezone.utc)` stays timezone-aware -- subtracting or comparing the two raises
`TypeError: can't subtract offset-naive and offset-aware datetimes`. This was found this session
via a real crash running anomaly checks against a sensor with real ingested history, and fixed
with a small `_as_aware_utc()` helper (a no-op if `tzinfo` is already set, otherwise it attaches
UTC) duplicated in `anomaly_service.py`, `sensor_ingestion_service.py`, and
`sensor_health_service.py` -- the same pattern already established in `user_service.py` from an
earlier work. In `anomaly_service.py` specifically, `check_missing_heartbeat` compares a
DB-read `last_valid_observed_at` against a freshly computed `now`; without the fix, every missed
heartbeat check against a sensor with any real history would have crashed rather than correctly
reporting elapsed time.

## Test coverage

`tests/test_sensor_statistics_and_anomaly.py` (anomaly half): range violation detected and
correctly reported insufficient (not falsely passed) with no configured range; rolling z-score
reporting insufficient baseline honestly, detecting a real outlier with sufficient baseline, and
staying silent within threshold; a zero-variance baseline reported as undefined rather than
crashing; MAD detecting an outlier; rate-of-change correctly reporting "no previous value" as a
reason rather than a candidate, and reporting insufficient baseline; missing-heartbeat candidates
for never-connected, within-interval (no candidate), and exceeded-interval cases; repeated-value
and sampling-gap anomalies detected; and a direct assertion that no anomaly severity string
sounds like a threat label.

`tests/test_anomaly_service.py`: range violation detected against a real persisted series;
`run_checks` idempotent for the same observation; insufficient baseline reported for a short
series; no-history sensors only running the heartbeat check; `review_anomaly` setting
`analyst_confirmed`/`data_quality` category correctly for `confirmed_unusual`/
`data_quality_issue` review statuses; an invalid `review_status` rejected; and anomaly listing
filtered by sensor and review status.
