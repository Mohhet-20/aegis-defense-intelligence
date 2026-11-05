# Time-Series Query, Downsampling, and Descriptive Statistics (Sections 7-8)

## Status

Implemented and tested: `app/services/timeseries_service.py` (98% coverage,
`tests/test_timeseries_service.py`) and `app/sensors/statistics.py` (99% coverage,
`tests/test_sensor_statistics_and_anomaly.py`), exposed via
`GET /sensor-analytics/sensors/{sensor_id}/timeseries` and
`GET /sensor-analytics/sensors/{sensor_id}/statistics` (both `Permission.OBSERVATION_READ`) in
`app/api/routes/sensor_analytics.py`. Live-verified in the frontend's Sensor Time-Series Explorer.

## Bounded queries -- never an unbounded scan

Every query in `timeseries_service.py` is explicitly bounded; a caller cannot request an
unbounded history. `validate_time_range(since, until)` fills in sensible defaults (`until`
defaults to now, `since` to seven days before `until`) and raises `QueryRangeTooLargeError` for
a requested range wider than `SENSOR_MAX_QUERY_RANGE_DAYS` (90 days) -- it never silently
truncates a too-wide request; the caller gets a clear 400 error instead (the route maps both
`QueryRangeTooLargeError` and a plain `ValueError`, e.g. `since` after `until`, to
`HTTP_400_BAD_REQUEST`).

`fetch_series()` additionally caps the number of raw rows returned per call at
`SENSOR_MAX_RAW_SAMPLES` (1000), requesting `max_samples + 1` rows so it can detect truncation
(`was_truncated = len(rows) > max_samples`) without an extra `COUNT` query. `compute_statistics()`
deliberately does **not** go through this raw-sample cap -- it computes over the full
`[since, until]` window via its own query -- but that window is still bounded by
`validate_time_range()`'s 90-day ceiling, so it never scans an unbounded table either.

## Downsampling is deterministic striding, never averaging

`downsample(observations, target_points)` is a deterministic, stride-based sampler: it always
keeps the first and last point and every `stride`-th point in between, where
`stride = max(1, len(observations) // target_points)`. It never averages or smooths points
together -- Section 7's "do not imply downsampled data preserves every transient event" is
enforced by construction: a stride sample is honestly a *subset* of real, observed points, never
a synthetic blend of them.

## Honesty discipline: `aggregation_note` and `is_downsampled` are never hidden

`GET /sensor-analytics/sensors/{id}/timeseries` (`get_timeseries` in `sensor_analytics.py`)
builds its `TimeSeriesResponse` with two fields that are always populated honestly, never
silently left for the caller to miss:

- `is_downsampled: bool` -- `True` whenever either downsampling kicked in (more rows in range
  than `max_points`, the request's own `1..5000` bounded query parameter, default 500) or the
  `SENSOR_MAX_RAW_SAMPLES` cap truncated the fetch.
- `aggregation_note: Optional[str]` -- a human-readable explanation of exactly what happened,
  e.g. `"deterministically stride-sampled to {n} of {total} points in range -- not every
  transient value is shown"` when downsampled to `max_points`, or `"query range contains more
  than the {SENSOR_MAX_RAW_SAMPLES}-sample cap; results were truncated, not averaged"` when the
  raw cap truncated the fetch before downsampling was even considered.

The response also always carries `total_in_range` (a true count, independent of what was
actually returned) and `returned_count`, so a client can always tell exactly how much of the real
data it is looking at.

### The frontend never hides this either

There is no charting library in the frontend (`frontend/package.json` only lists `react`,
`react-dom`, and `react-router-dom`). The Sensor Time-Series Explorer's chart
(`TimeSeriesChart` in `frontend/src/pages/SensorDetailPage.tsx`) is a hand-rolled inline SVG
component: it colors each point by `validation_status` (`valid` green, `valid_with_warnings`/
`stale` amber, `invalid`/`incomplete` red, `out_of_range` orange, `duplicate` gray, matching
`QUALITY_STATUS_COLOR`), draws a legend for those colors, and shows a `<title>` hover tooltip
per point with the observed value, unit, validation status, and any quality flags. Directly
below the chart it renders `series.aggregation_note` verbatim whenever it is present, plus a
line stating `"{returned_count} of {total_in_range} points in range shown"` with the actual
`since`/`until` window -- the truncation/downsampling story the backend computed is surfaced to
the analyst exactly as computed, never quietly dropped because there was no charting library to
hand it to.

## Descriptive statistics (`app/sensors/statistics.py`)

`compute_descriptive_statistics(series, ...)` is a pure function over an already-fetched,
bounded list of `TimedValue(observed_at, value, is_valid)` entries -- no database access, no
unbounded scans; `timeseries_service.py` owns the bounded query, this module only computes over
what it's given, and `series` must already be sorted ascending (the caller's `ORDER BY` query
guarantees this). It never raises for empty or degenerate input; it returns an explicit
`insufficient_sample=True` shape instead (zero valid points, or fewer than two).

Computed fields on `DescriptiveStatistics`: `valid_count`/`invalid_count`, `minimum`/`maximum`,
`mean` (`statistics.fmean`), `median`, `stdev_sample` (sample stdev, only once &ge;2 valid
points exist), `percentiles` (a dict keyed `p50`/`p90`/`p95`/`p99` by default, only once &ge;2
points exist), `latest_valid_value`/`latest_valid_observed_at`, `rate_of_change_per_second`
(change between the latest two valid points divided by elapsed seconds, only when elapsed > 0),
and a `gap_summary` (`GapSummary`: `gap_count`, `max_gap_seconds`, and `missing_frame_like` --
true only once a `nominal_interval_seconds` was supplied, since without one "missing" has no
defined meaning; `gap_count` then counts gaps exceeding 1.5x that nominal interval). Every
`DescriptiveStatistics` also carries its own `method_version` (`STATISTICS_METHOD_VERSION`,
currently `"1.0"`).

### A fixed bug: the docstring's promise didn't match the input path

The module's docstring states NaN/infinity are "never returned as a summary value," backed by a
`_finite_or_none()` helper applied to every output. Originally, though, that sanitization only
ran on *outputs* -- the raw `valid` list built from the input series was never filtered for
non-finite values before being handed to `statistics.stdev()`/`statistics.fmean()`, both of which
raise on NaN/infinite input before `_finite_or_none` ever gets a chance to run on their result.
The fix filters the `valid` list itself (excluding any point whose value is NaN or infinite)
before any aggregate is computed at all, so the docstring's promise now actually holds for every
code path, not just the ones that got as far as producing an output.

## Test coverage

`tests/test_timeseries_service.py`: `validate_time_range` defaulting to 7 days, rejecting
`since` after `until`, and rejecting a too-wide range; `fetch_series` returning real ingested
observations and honestly reporting truncation; `downsample` keeping the first/last point and
no-op'ing when already under target; `compute_statistics` over a real series and over an empty
window (insufficient sample).

`tests/test_sensor_statistics_and_anomaly.py` (statistics half): an empty series and a
single-point series both reported `insufficient_sample` (the latter not counted as fully empty);
basic descriptive statistics against known values; invalid points excluded from the aggregate;
rate of change computed between the last two points; gap summary detecting a gap exceeding the
nominal interval; and a dedicated non-finite-input regression test asserting no NaN/infinite
value is ever returned.
