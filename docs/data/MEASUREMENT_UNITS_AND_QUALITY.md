# Measurement Units and Quality (Sections 6 and 12)

## Status

Implemented and tested: `app/sensors/units.py` (100% coverage, `tests/test_sensor_units.py`) and
`app/sensors/quality.py` (98% coverage, `tests/test_sensor_quality.py`). Both are pure functions
with no database access -- the caller (`app/services/sensor_ingestion_service.py`) supplies
whatever historical context a check needs (recent values, the latest prior `observed_at`) rather
than either module querying for it, which is what keeps every check independently unit-testable.

## Unit conversion (`app/sensors/units.py`)

A small, **closed** table of supported units grouped by physical dimension:
`temperature` (`celsius`, `fahrenheit`, `kelvin`), `length` (`meters`, `kilometers`, `feet`,
`miles`), `speed` (`meters_per_second`, `kilometers_per_hour`, `miles_per_hour`), `mass`
(`kilograms`, `pounds`), `pressure` (`hectopascals`, `pascals`, `psi`), `angle` (`degrees`,
`radians`), and `ratio` (`percent`, `fraction`). Every linear dimension converts through one
canonical base unit via a simple multiplicative factor; temperature uses its own affine
functions (`celsius = (fahrenheit - 32) * 5/9`, `celsius = kelvin - 273.15`) since Celsius and
Fahrenheit are not linear through zero. `convert_unit(value, from_unit, to_unit)` returns a
`ConversionResult` carrying both the original and converted value plus `rule_version` (currently
`"1.0"`) -- the converted value is rounded to 6 decimal places for display, but since the
original, full-precision value is also returned, a caller that needs exactness can recompute
rather than lose precision to the rounding (Section 12: "handle rounding transparently," never
silently).

Converting between units of different physical dimensions (e.g. `celsius` to `meters`), or
referencing a unit outside the closed table, always raises `IncompatibleUnitError` -- there is no
fallback or best-guess behavior. `units_compatible(unit_a, unit_b)` is the non-raising sibling
used by the quality layer below: it returns `False` for an unrecognized unit on either side
rather than raising, since a quality check needs a yes/no answer, not an exception.

This module **never invents a calibration coefficient**. It performs only standard, documented
unit-system conversions; a sensor-specific calibration correction (e.g. "this particular
thermometer reads 1.2 degrees high") is a separate, per-sensor fact that would have to come from
the sensor's own documented configuration, and there is no mechanism here to apply one that
wasn't supplied -- satisfying Section 12's "avoid applying calibration coefficients that are not
documented for the source."

## Quality classification (`app/sensors/quality.py`)

Every check here answers a **quality** question (did this parse, is it fresh, is it in range) --
never a truth/threat question. An observation classified `out_of_range` or `stale` is not thereby
wrong, dangerous, or hostile; it is a data-quality flag an analyst can inspect, same as
`app/sensors/anomaly.py`'s candidates (see `docs/analytics/ANOMALY_DETECTION.md`).

`evaluate_observation()` is the single entry point `sensor_ingestion_service.py` calls for every
candidate record. It runs each applicable check below, collects every `QualityIssue` (a `code`,
a human-readable `message`, and `is_error: bool`), and returns one `QualityOutcome`:

| Check | QualityIssue code(s) | `is_error` |
|---|---|---|
| `check_required_fields` | `missing_required_field` (one of `sensor_id`/`measurement_type`/`observed_at` missing or empty) | True |
| `check_timestamp` | `invalid_timestamp` | True |
| `check_numeric_value` | `non_numeric_value`, `non_finite_value` (NaN/infinity) | True |
| `check_unit` | `unit_incompatible` (different physical dimension) | True |
| `check_unit` | `unit_mismatch_convertible` (reported unit differs from the sensor's configured unit but is convertible) | False |
| `check_range` | `below_configured_minimum`, `above_configured_maximum` | False |
| `check_freshness` | `stale_observation` (age vs. `ingested_at` exceeds `stale_after_seconds`, default 86400.0) | False |
| `check_out_of_order` | `out_of_order_arrival` (earlier than the latest prior observation already ingested) | False |
| `check_repeated_value` | `excessive_repeated_value` (identical run length &ge; `max_identical_run`, default 5) | False |
| `check_sampling_gap` | `unexpected_sampling_gap` (gap since the prior observation exceeds `nominal_interval_seconds * missed_multiple`, default multiple 3.0) | False |

`check_numeric_value` treats a genuinely absent value (`raw_value is None`) as not an error at
all -- a structured (non-numeric) observation legitimately has no numeric value, and returning
`(None, [])` for it keeps Section 4's "never interpret missing data as a numeric zero" intact.
Only a value that *is* present but fails to parse, or parses to NaN/infinity, is rejected.

`classify(issues)` maps the collected issues to one of the seven `OBSERVATION_VALIDATION_STATUSES`
(`valid`, `valid_with_warnings`, `invalid`, `stale`, `duplicate`, `incomplete`, `out_of_range`) by
precedence: any error wins and the record is `invalid`; otherwise `missing_required_field` wins to
`incomplete`, then `stale_observation` to `stale`, then a range violation to `out_of_range`;
anything left with only generic warnings is `valid_with_warnings`; no issues at all is `valid`.
A record can still carry multiple `quality_flags` regardless of which single status wins --
the flags list, not the single status, is the complete picture. Only an outright error blocks
persistence of the `Observation` itself (`is_accepted = status != "invalid" and observed_at is
not None`); every other finding is still a real, inspectable row, just flagged. The corresponding
`RawRecord` quarantine reference is always created regardless of `is_accepted` (Section 6: "do
not silently discard problematic records").

## Two bugs this session's test run caught

`check_timestamp()` previously declared a 3-tuple return but every caller only unpacked two
values, so it crashed on every single observation until it was fixed to actually return the
`(datetime | None, list[QualityIssue])` 2-tuple its callers expected -- a plain return-arity bug,
caught the moment a real ingestion batch was run end to end rather than only against a mocked
caller.

`app/sensors/statistics.py`'s `compute_descriptive_statistics()` is documented as never returning
NaN/infinity as a summary value, but originally only sanitized its *output* values (via
`_finite_or_none`) without first filtering non-finite values out of its *input* -- `statistics.
stdev()`/`statistics.fmean()` raise on NaN/infinite input before any output sanitization gets a
chance to run. The fix filters the `valid` list itself to exclude non-finite values before any
aggregate is computed, closing the gap between the docstring's promise and what the code actually
did; see `docs/analytics/TIME_SERIES_ANALYTICS.md` for the statistics module itself.

## Test coverage

`tests/test_sensor_units.py`: identity conversion for the same unit, Celsius-to-Fahrenheit and
Celsius-to-Kelvin, kilometers-to-meters and a miles-to-feet round trip, speed kph-to-mps,
incompatible-dimension and unrecognized-unit errors, `units_compatible` true/false/never-raises,
and an assertion that no calibration coefficient ever appears in a `ConversionResult`.

`tests/test_sensor_quality.py`: a fully valid record accepted; a missing required field classified
`incomplete` and rejected; an unparseable timestamp and a non-numeric value both classified
`invalid` and rejected; a genuinely missing (structured) value treated as not an error; an
out-of-range and a below-minimum value both flagged but still accepted; a stale observation
flagged but accepted; an incompatible unit rejected as invalid vs. a convertible unit mismatch
only warned; repeated-value runs flagged at and below threshold; out-of-order arrival flagged as
a warning; a sampling gap flagged when it exceeds threshold; multiple simultaneous errors still
resolving to `invalid`; and `QualityOutcome` rejecting an unknown `validation_status` at
construction time.
