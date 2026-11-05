# Canonical Sensor Observation Schema

**Status: REAL.** the `Observation` storage shape plus the
(Section 4) extensions migrated in `e416c9a24fa4`. This supersedes
`docs/architecture/MULTISENSOR_CONTRACTS.md`'s description of
`quality_metadata` as "present, not yet populated by any real quality
computation" -- it is now populated by `app/sensors/quality.py` on every
ingested record. `SENSOR_OBSERVATION_SCHEMA_VERSION = "1.0"`
(`app/models/observation.py`), stored on every row via `schema_version`,
bumped whenever a change to validation/normalization would affect how an
already-stored row should be interpreted.

## Fields (`app/models/observation.py`)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID string | generated |
| `organization_id` | string | required, FK |
| `sensor_id` | string, nullable | FK `sensors.id`, `ON DELETE SET NULL` |
| `source_id` | string, nullable | FK `data_sources.id` |
| `observed_at` | datetime, tz-aware UTC | event time -- always a distinct column from `ingested_at` |
| `observation_type` | string | doubles as the measurement-type identifier for numeric telemetry (e.g. `"temperature_c"`); no separate `measurement_type` column was added |
| `payload` | JSON dict | the generic structured value the non-numeric rows already used, plus every field from an ingested record that isn't one of the dedicated columns below -- see `_RESERVED_KEYS` in `sensor_ingestion_service.py` |
| `quality_metadata` | JSON dict | `{"issues": [...], "ruleset_version": ...}` -- the full list of `QualityIssue` codes/messages produced for this row, not just the single `validation_status` that won |
| `provenance` | JSON dict | `raw_record_id`, `connector_type`, `connector_version`, `schema_version`, `content_fingerprint`, `quality_ruleset_version` |
| `processing_status` | string | `ingested` / `associated` / `archived` (`OBSERVATION_PROCESSING_STATUSES`) |
| `data_origin` | string | `synthetic_demo` / `user_upload` -- never lets a synthetic record pass as a live feed |
| `ingested_at` | datetime, tz-aware UTC, nullable | When this platform actually processed the record. Nullable at the DB level only so the three pre-existing original seed rows stay valid without a backfill; the ingestion service always sets it for every row it creates. |
| `measurement_value` | float, nullable | The explicit numeric value the statistics/anomaly engines operate on. `None` for a structured-only observation -- never a fabricated `0.0`. |
| `unit` | string, nullable | The record's reported unit, or the sensor's configured unit for this measurement type if the record didn't supply one. |
| `validation_status` | string | One of `OBSERVATION_VALIDATION_STATUSES` -- see "Validation statuses" below. Default `"valid"` (server-defaulted on migration for the 3 pre-existing seed rows). |
| `quality_flags` | JSON list | Every `QualityIssue.code` produced for this record (e.g. `["stale_observation", "below_configured_minimum"]`) -- a record can carry multiple flags regardless of which single `validation_status` wins. |
| `source_record_id` | string, nullable | FK `raw_records.id`, `ON DELETE SET NULL`. The `RawRecord` this observation was normalized from. `NULL` for the 3 original seed rows and any future hand-created observation. |
| `ingestion_job_id` | string, nullable | FK `ingestion_jobs.id`, `ON DELETE SET NULL`. |
| `schema_version` | string | Default `"1.0"`. |
| `calibration_metadata` | JSON dict, nullable | Populated only when the source itself supplied it (via `record["calibration_metadata"]`) or a documented, versioned unit conversion ran (`app/sensors/units.py`) -- never invented. |
| `uncertainty_metadata` | JSON dict, nullable | Same policy -- both `None` unless the source documented them. |

## Validation statuses (`OBSERVATION_VALIDATION_STATUSES`)

A flat, documented set rather than a single pass/fail bit, because "valid
with warnings" and "stale" are deliberately NOT the same thing as "invalid"
(Section 6's required distinction between a validation failure and an
unusual-but-maybe-valid measurement):

| Status | Meaning |
|---|---|
| `valid` | no issues found |
| `valid_with_warnings` | one or more non-error issues, none of the specific categories below |
| `invalid` | at least one error-level issue (missing required field, unparseable timestamp, non-numeric/non-finite value, incompatible unit) -- blocks persistence as an `Observation` entirely |
| `stale` | `observed_at` is older than `ingested_at` by more than `SENSOR_STALE_AFTER_SECONDS` (86400.0 default) |
| `duplicate` | reserved status value in the enum; the ingestion pipeline currently represents a duplicate on `RawRecord.is_duplicate` rather than ever writing an `Observation` with this `validation_status` |
| `incomplete` | a required field (`sensor_id`, `measurement_type`, `observed_at`) was missing or empty |
| `out_of_range` | value is outside the sensor's configured `operating_range` for that measurement type |

Precedence when multiple issues apply (`app/sensors/quality.classify()`,
most to least severe): any error -> `invalid`; then `incomplete`; then
`stale`; then `out_of_range`; then, if any other warning remains,
`valid_with_warnings`; otherwise `valid`.

Only an outright error blocks persistence -- every other finding still
becomes a real, inspectable `Observation`, just flagged
(`is_accepted = status != "invalid" and observed_at is not None`). A record
is never silently discarded: the `RawRecord` quarantine reference is always
written regardless of whether an `Observation` is also created.

## The quality-issue model (`app/sensors/quality.py`)

Every check is a pure function returning zero or more `QualityIssue(code,
message, is_error)` values -- no database access; the caller
(`sensor_ingestion_service.py`) supplies whatever historical context a check
needs (recent values, the latest prior `observed_at`) so each check stays
independently unit-testable. The checks, in the order
`evaluate_observation()` runs them:

| Check | Produces |
|---|---|
| `check_required_fields` | `missing_required_field` (error) for a missing/empty `sensor_id`/`measurement_type`/`observed_at` |
| `check_timestamp` | `invalid_timestamp` (error) if `observed_at` can't be parsed |
| `check_numeric_value` | `non_numeric_value` / `non_finite_value` (error) -- a bad value is rejected, never coerced to `0.0`; a genuinely absent value (`None`) is not an error |
| `check_unit` | `unit_mismatch_convertible` (warning) if the reported unit differs from the sensor's configured unit but is convertible; `unit_incompatible` (error) if the two units are a different physical dimension |
| `check_range` | `below_configured_minimum` / `above_configured_maximum` (warning) against `Sensor.operating_range` |
| `check_freshness` | `stale_observation` (warning) if older than `stale_after_seconds` |
| `check_out_of_order` | `out_of_order_arrival` (warning) if earlier than the most recently ingested observation for this sensor+measurement |
| `check_repeated_value` | `excessive_repeated_value` (warning) if the value repeats `>= max_identical_run` times in a row |
| `check_sampling_gap` | `unexpected_sampling_gap` (warning) if the gap since the prior observation exceeds `missed_multiple x nominal_interval_seconds` |

A quality question (did this parse, is it fresh, is it in range) is never a
truth/threat question -- a record classified `out_of_range` or `stale` is not
thereby wrong, dangerous, or hostile.

## Timestamp normalization

`check_timestamp()` delegates to `app/services/normalization_service.
normalize_timestamp()` (the same function the Event pipeline already
uses): a value with explicit timezone/offset is converted to UTC as given; a
naive value is assumed to already be UTC; epoch seconds (`int`/`float`) are
unambiguous and parsed as UTC; anything that doesn't parse becomes
`invalid_timestamp`, never defaulted to "now." `Observation.sensor_timezone`
is configured per sensor (`Sensor.sensor_timezone`, default `"UTC"`) but is
metadata for display/interpretation only -- normalization itself always
converts to UTC before storage.

## Raw records vs. canonical observations

Every ingested record, regardless of outcome, produces exactly one
`RawRecord` (`app/models/raw_record.py`) -- the quarantine/provenance
reference, preserved verbatim including a `content_fingerprint`. A
corresponding `Observation` is created **only if** `QualityOutcome.
is_accepted` is `True`. A duplicate record (matched by `external_id`, either
repeated earlier in the same batch or against a previously-ingested record
for the same source) gets a `RawRecord` with `is_duplicate=True` and no
`Observation` at all -- `RawRecord.is_duplicate` is the duplicate
signal; `Observation.validation_status = "duplicate"` is a reserved value
never actually written by the current pipeline. `RawRecord.event_id` always
stays `NULL` for a sensor batch (that column exists for the Event
pipeline); the sensor-specific link back is `Observation.source_record_id`.

```
sensor batch record
      |
      v
RawRecord (ALWAYS written: accepted / rejected / duplicate)
      |
      | (only if quality_lib.evaluate_observation().is_accepted)
      v
Observation  --source_record_id-->  RawRecord
             --ingestion_job_id -->  IngestionJob
```

## Downstream readers

- `app/sensors/statistics.py` / `app/services/timeseries_service.py` --
  descriptive statistics and time-series queries read `measurement_value`,
  `unit`, `validation_status`, `observed_at` directly; a non-`valid`/
  `valid_with_warnings` row is excluded from the "valid" series but still
  counted in `invalid_count`.
- `app/sensors/anomaly.py` / `app/services/anomaly_service.py` -- anomaly
  checks read a sensor+measurement type's recent `measurement_value`/
  `observed_at` history (rows with a non-`NULL` `measurement_value` only) and
  persist findings as `ObservationAnomaly` (see
  `docs/architecture/SENSOR_DATA_ARCHITECTURE.md`), never by rewriting the
  `Observation` row itself.

## What this does NOT do

- No numeric value is ever fabricated for a structured-only observation --
  `measurement_value` stays `None`.
- No calibration coefficient is invented; `calibration_metadata` is `None`
  unless the source supplied one or a documented unit conversion ran.
- No unit conversion is applied silently -- an incompatible unit is an
  `invalid` error, never a guess (see `app/sensors/units.py`).
- `Observation.validation_status = "duplicate"` is defined in the enum but
  not currently produced by any code path -- duplicates are represented on
  `RawRecord.is_duplicate` instead, as documented above.
