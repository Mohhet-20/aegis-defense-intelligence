"""Unit tests for app/sensors/quality.py -- the
pure measurement-validation/quality-classification layer. No DB access.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.sensors import quality as quality_lib

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _record(**overrides) -> dict:
    base = {
        "sensor_id": "sensor-1",
        "measurement_type": "temperature_c",
        "value": 22.0,
        "unit": "celsius",
        "observed_at": NOW.isoformat(),
    }
    base.update(overrides)
    return base


def test_valid_record_accepted():
    outcome = quality_lib.evaluate_observation(_record(), ingested_at=NOW)
    assert outcome.validation_status == "valid"
    assert outcome.is_accepted is True
    assert outcome.quality_flags == []
    assert outcome.normalized_value == 22.0
    assert outcome.normalized_observed_at == NOW


def test_missing_required_field_is_incomplete_and_rejected():
    record = _record()
    del record["measurement_type"]
    outcome = quality_lib.evaluate_observation(record, ingested_at=NOW)
    assert outcome.validation_status == "invalid"
    assert outcome.is_accepted is False
    assert "missing_required_field" in outcome.quality_flags


def test_unparseable_timestamp_is_invalid_and_rejected():
    outcome = quality_lib.evaluate_observation(_record(observed_at="not-a-timestamp"), ingested_at=NOW)
    assert outcome.validation_status == "invalid"
    assert outcome.is_accepted is False
    assert outcome.normalized_observed_at is None
    assert "invalid_timestamp" in outcome.quality_flags


def test_non_numeric_value_is_invalid():
    outcome = quality_lib.evaluate_observation(_record(value="not-a-number"), ingested_at=NOW)
    assert outcome.validation_status == "invalid"
    assert outcome.is_accepted is False
    assert "non_numeric_value" in outcome.quality_flags


def test_missing_value_is_not_an_error_structured_observation():
    """A structured (non-numeric) observation legitimately has no
    numeric value -- that alone must never make it invalid."""
    record = _record()
    del record["value"]
    outcome = quality_lib.evaluate_observation(record, ingested_at=NOW)
    assert outcome.validation_status == "valid"
    assert outcome.is_accepted is True
    assert outcome.normalized_value is None


def test_out_of_range_value_is_flagged_but_still_accepted():
    outcome = quality_lib.evaluate_observation(
        _record(value=99.0), ingested_at=NOW, operating_range={"min": -10.0, "max": 45.0},
    )
    assert outcome.validation_status == "out_of_range"
    assert outcome.is_accepted is True  # a range breach is a quality flag, not a rejection
    assert "above_configured_maximum" in outcome.quality_flags


def test_below_minimum_value_is_flagged():
    outcome = quality_lib.evaluate_observation(
        _record(value=-99.0), ingested_at=NOW, operating_range={"min": -10.0, "max": 45.0},
    )
    assert outcome.validation_status == "out_of_range"
    assert "below_configured_minimum" in outcome.quality_flags


def test_stale_observation_flagged_but_accepted():
    old = NOW - timedelta(days=5)
    outcome = quality_lib.evaluate_observation(
        _record(observed_at=old.isoformat()), ingested_at=NOW, stale_after_seconds=86400.0,
    )
    assert outcome.validation_status == "stale"
    assert outcome.is_accepted is True
    assert "stale_observation" in outcome.quality_flags


def test_incompatible_unit_is_invalid():
    outcome = quality_lib.evaluate_observation(
        _record(unit="meters"), ingested_at=NOW, configured_unit="celsius",
    )
    assert outcome.validation_status == "invalid"
    assert outcome.is_accepted is False
    assert "unit_incompatible" in outcome.quality_flags


def test_convertible_unit_mismatch_is_a_warning_not_a_rejection():
    outcome = quality_lib.evaluate_observation(
        _record(unit="fahrenheit"), ingested_at=NOW, configured_unit="celsius",
    )
    assert outcome.is_accepted is True
    assert "unit_mismatch_convertible" in outcome.quality_flags
    assert outcome.validation_status == "valid_with_warnings"


def test_repeated_value_run_flagged():
    outcome = quality_lib.evaluate_observation(
        _record(value=20.0), ingested_at=NOW, recent_values=[20.0, 20.0, 20.0, 20.0, 20.0], max_identical_run=5,
    )
    assert "excessive_repeated_value" in outcome.quality_flags
    assert outcome.is_accepted is True


def test_repeated_value_below_threshold_not_flagged():
    outcome = quality_lib.evaluate_observation(
        _record(value=20.0), ingested_at=NOW, recent_values=[20.0, 20.0], max_identical_run=5,
    )
    assert "excessive_repeated_value" not in outcome.quality_flags


def test_out_of_order_arrival_flagged_as_warning():
    later = NOW
    earlier = NOW - timedelta(minutes=5)
    outcome = quality_lib.evaluate_observation(
        _record(observed_at=earlier.isoformat()), ingested_at=NOW, latest_prior_observed_at=later,
    )
    assert "out_of_order_arrival" in outcome.quality_flags
    assert outcome.is_accepted is True  # a warning, not a rejection


def test_sampling_gap_flagged_when_exceeding_threshold():
    prior = NOW - timedelta(seconds=1000)
    outcome = quality_lib.evaluate_observation(
        _record(observed_at=NOW.isoformat()), ingested_at=NOW,
        latest_prior_observed_at=prior, nominal_interval_seconds=60.0, missed_multiple=3.0,
    )
    assert "unexpected_sampling_gap" in outcome.quality_flags


def test_classify_multiple_errors_still_invalid():
    record = _record(value="bad", observed_at="also-bad")
    del record["sensor_id"]
    outcome = quality_lib.evaluate_observation(record, ingested_at=NOW)
    assert outcome.validation_status == "invalid"
    assert len(outcome.quality_flags) >= 3


def test_quality_outcome_rejects_unknown_validation_status():
    import pytest as _pytest

    with _pytest.raises(AssertionError):
        quality_lib.QualityOutcome(validation_status="not_a_real_status")
