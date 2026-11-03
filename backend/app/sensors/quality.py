"""Measurement validation and quality classification (Phase 6, Section
6). Pure functions -- no database access. The caller
(app/services/sensor_ingestion_service.py) supplies whatever historical
context a check needs (e.g. the sensor's recent observations for a
repeated-value/gap check) rather than this module querying for it,
keeping every check here independently unit-testable.

Every check here answers a QUALITY question (did this parse, is it
fresh, is it in range) -- never a truth/threat question. An observation
classified "out_of_range" or "stale" is not thereby wrong, dangerous,
or hostile; see docs/data/MEASUREMENT_UNITS_AND_QUALITY.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.models.observation import OBSERVATION_VALIDATION_STATUSES
from app.sensors import units as unit_lib
from app.services import normalization_service as norm

QUALITY_RULESET_VERSION = "1.0"


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str
    is_error: bool  # True => record cannot be accepted as "valid"/"valid_with_warnings"


@dataclass
class QualityOutcome:
    validation_status: str
    quality_flags: list[str] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    normalized_observed_at: Optional[datetime] = None
    normalized_value: Optional[float] = None
    is_accepted: bool = True  # False => quarantine, never persisted as an Observation

    def __post_init__(self) -> None:
        assert self.validation_status in OBSERVATION_VALIDATION_STATUSES


REQUIRED_FIELDS = ("sensor_id", "measurement_type", "observed_at")


def check_required_fields(record: dict) -> list[QualityIssue]:
    issues = []
    for field_name in REQUIRED_FIELDS:
        value = record.get(field_name)
        if value in (None, ""):
            issues.append(QualityIssue("missing_required_field", f"required field '{field_name}' is missing or empty", is_error=True))
    return issues


def check_timestamp(raw_observed_at: object) -> tuple[Optional[datetime], list[QualityIssue]]:
    normalized = norm.normalize_timestamp(raw_observed_at)
    if normalized.value is None:
        return None, [QualityIssue("invalid_timestamp", f"observed_at could not be parsed: {raw_observed_at!r}", is_error=True)]
    return normalized.value, []


def check_numeric_value(raw_value: object) -> tuple[Optional[float], list[QualityIssue]]:
    """Returns (parsed_value_or_None, issues). A structured (non-numeric)
    observation legitimately has no numeric value at all -- that is
    NOT an error; `raw_value is None` returns (None, []). A value that
    IS present but doesn't parse as a finite number is an error --
    Section 4's "never interpret missing data as a numeric zero" and
    Section 8's "never display NaN/infinity as if meaningful" both
    apply here: a bad numeric value is rejected, never coerced to 0.0."""
    if raw_value is None:
        return None, []
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        return None, [QualityIssue("non_numeric_value", f"measurement value could not be parsed as a number: {raw_value!r}", is_error=True)]
    if math.isnan(parsed) or math.isinf(parsed):
        return None, [QualityIssue("non_finite_value", f"measurement value is not finite: {raw_value!r}", is_error=True)]
    return parsed, []


def check_unit(unit: Optional[str], *, configured_unit: Optional[str]) -> list[QualityIssue]:
    """Warns (never rejects) when a record reports a unit different
    from the sensor's configured unit for this measurement type, UNLESS
    the two units are outright incompatible (different physical
    dimension), which IS an error -- Section 4: "never silently change
    units without recording the conversion," so an incompatible unit is
    refused rather than guessed at."""
    if not unit or not configured_unit or unit == configured_unit:
        return []
    if unit_lib.units_compatible(unit, configured_unit):
        return [QualityIssue("unit_mismatch_convertible", f"reported unit '{unit}' differs from the sensor's configured unit '{configured_unit}' but is convertible", is_error=False)]
    return [QualityIssue("unit_incompatible", f"reported unit '{unit}' is incompatible with the sensor's configured unit '{configured_unit}'", is_error=True)]


def check_range(value: Optional[float], *, operating_range: Optional[dict]) -> list[QualityIssue]:
    if value is None or not operating_range:
        return []
    low = operating_range.get("min")
    high = operating_range.get("max")
    if low is not None and value < low:
        return [QualityIssue("below_configured_minimum", f"value {value} is below the configured minimum {low}", is_error=False)]
    if high is not None and value > high:
        return [QualityIssue("above_configured_maximum", f"value {value} is above the configured maximum {high}", is_error=False)]
    return []


def check_freshness(observed_at: Optional[datetime], *, ingested_at: datetime, stale_after_seconds: float) -> list[QualityIssue]:
    if observed_at is None:
        return []
    age = (ingested_at - observed_at).total_seconds()
    if age > stale_after_seconds:
        return [QualityIssue("stale_observation", f"observed_at is {age:.0f}s older than ingested_at (stale_after_seconds={stale_after_seconds})", is_error=False)]
    return []


def check_out_of_order(observed_at: Optional[datetime], *, latest_prior_observed_at: Optional[datetime]) -> list[QualityIssue]:
    if observed_at is None or latest_prior_observed_at is None:
        return []
    if observed_at < latest_prior_observed_at:
        return [QualityIssue("out_of_order_arrival", f"observed_at {observed_at.isoformat()} is earlier than the most recently ingested observation for this sensor+measurement ({latest_prior_observed_at.isoformat()})", is_error=False)]
    return []


def check_repeated_value(value: Optional[float], *, recent_values: list[Optional[float]], max_identical_run: int) -> list[QualityIssue]:
    """`recent_values` is the sensor's last N values for this
    measurement type, most-recent-last, NOT including the candidate
    `value` itself."""
    if value is None or not recent_values:
        return []
    run = 0
    for prior in reversed(recent_values):
        if prior == value:
            run += 1
        else:
            break
    if run >= max_identical_run:
        return [QualityIssue("excessive_repeated_value", f"value {value} repeats {run + 1} times in a row (threshold {max_identical_run})", is_error=False)]
    return []


def check_sampling_gap(
    observed_at: Optional[datetime],
    *,
    latest_prior_observed_at: Optional[datetime],
    nominal_interval_seconds: Optional[float],
    missed_multiple: float,
) -> list[QualityIssue]:
    if observed_at is None or latest_prior_observed_at is None or not nominal_interval_seconds:
        return []
    gap = (observed_at - latest_prior_observed_at).total_seconds()
    threshold = nominal_interval_seconds * missed_multiple
    if gap > threshold > 0:
        return [QualityIssue("unexpected_sampling_gap", f"{gap:.0f}s since the previous observation exceeds {missed_multiple}x the nominal interval ({nominal_interval_seconds:.0f}s)", is_error=False)]
    return []


def classify(issues: list[QualityIssue]) -> str:
    """Maps a list of issues to one OBSERVATION_VALIDATION_STATUSES
    value. Precedence (most to least severe): any error -> 'invalid';
    then the specific warning categories Section 6 explicitly names;
    anything else with only generic warnings -> 'valid_with_warnings';
    no issues -> 'valid'. A record can carry MULTIPLE quality_flags
    regardless of which single status wins here -- the flags list (not
    this single status) is the complete picture."""
    if any(issue.is_error for issue in issues):
        return "invalid"
    codes = {issue.code for issue in issues}
    if "missing_required_field" in codes:
        return "incomplete"
    if "stale_observation" in codes:
        return "stale"
    if {"below_configured_minimum", "above_configured_maximum"} & codes:
        return "out_of_range"
    if issues:
        return "valid_with_warnings"
    return "valid"


def evaluate_observation(
    record: dict,
    *,
    ingested_at: datetime,
    configured_unit: Optional[str] = None,
    operating_range: Optional[dict] = None,
    recent_values: Optional[list[Optional[float]]] = None,
    latest_prior_observed_at: Optional[datetime] = None,
    nominal_interval_seconds: Optional[float] = None,
    stale_after_seconds: float = 86400.0,
    missed_multiple: float = 3.0,
    max_identical_run: int = 5,
) -> QualityOutcome:
    """The single entry point app/services/sensor_ingestion_service.py
    calls for every candidate record. Runs every applicable check and
    returns one QualityOutcome -- never raises for an ordinary bad
    record (only a programmer error would raise)."""
    issues = list(check_required_fields(record))

    observed_at, ts_issues = check_timestamp(record.get("observed_at"))
    issues += ts_issues

    value, value_issues = check_numeric_value(record.get("value"))
    issues += value_issues

    issues += check_unit(record.get("unit"), configured_unit=configured_unit)
    issues += check_range(value, operating_range=operating_range)

    if observed_at is not None:
        issues += check_freshness(observed_at, ingested_at=ingested_at, stale_after_seconds=stale_after_seconds)
        issues += check_out_of_order(observed_at, latest_prior_observed_at=latest_prior_observed_at)
        issues += check_sampling_gap(
            observed_at,
            latest_prior_observed_at=latest_prior_observed_at,
            nominal_interval_seconds=nominal_interval_seconds,
            missed_multiple=missed_multiple,
        )
    if value is not None:
        issues += check_repeated_value(value, recent_values=recent_values or [], max_identical_run=max_identical_run)

    status = classify(issues)
    # Only an outright error (missing required field, unparseable
    # timestamp, non-numeric/non-finite value, incompatible unit) blocks
    # persistence entirely -- every other finding is still a real,
    # inspectable Observation, just flagged ("do not silently
    # discard problematic records"). The RawRecord quarantine reference
    # is ALWAYS created regardless (see sensor_ingestion_service.py);
    # only whether a corresponding Observation is also created depends
    # on this flag.
    is_accepted = status != "invalid" and observed_at is not None

    return QualityOutcome(
        validation_status=status,
        quality_flags=[issue.code for issue in issues],
        issues=issues,
        normalized_observed_at=observed_at,
        normalized_value=value,
        is_accepted=is_accepted,
    )
