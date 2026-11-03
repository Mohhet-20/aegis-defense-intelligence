"""Tests for app/geo/validation.py (Phase 7, Section 17 "Coordinate
validation" and Section 10 "Location quality and uncertainty")."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.geo.validation import (
    FINDING_INVALID_RANGE,
    FINDING_MISSING,
    FINDING_NON_FINITE,
    FINDING_STALE_SOURCE_TIMESTAMP,
    FINDING_UNCERTAINTY_UNAVAILABLE,
    FINDING_UNSUPPORTED_CRS,
    FINDING_VALID,
    classify_validation_status,
    is_usable_for_mapping,
    validate_coordinates,
)


def test_valid_coordinates():
    findings = validate_coordinates(40.0, -73.0)
    codes = [f.code for f in findings]
    assert FINDING_VALID in codes
    assert FINDING_UNCERTAINTY_UNAVAILABLE in codes  # no uncertainty supplied


def test_valid_coordinates_with_uncertainty_supplied_has_no_unavailable_finding():
    findings = validate_coordinates(40.0, -73.0, location_uncertainty_m=25.0)
    codes = [f.code for f in findings]
    assert FINDING_VALID in codes
    assert FINDING_UNCERTAINTY_UNAVAILABLE not in codes


def test_missing_coordinates_latitude_none():
    findings = validate_coordinates(None, -73.0)
    assert len(findings) == 1
    assert findings[0].code == FINDING_MISSING
    assert findings[0].is_error is False


def test_missing_coordinates_longitude_none():
    findings = validate_coordinates(40.0, None)
    assert findings[0].code == FINDING_MISSING


def test_missing_coordinates_both_none():
    findings = validate_coordinates(None, None)
    assert findings[0].code == FINDING_MISSING


def test_out_of_range_latitude_too_high():
    findings = validate_coordinates(91.0, 0.0)
    assert findings[0].code == FINDING_INVALID_RANGE
    assert findings[0].is_error is True


def test_out_of_range_latitude_too_low():
    findings = validate_coordinates(-91.0, 0.0)
    assert findings[0].code == FINDING_INVALID_RANGE


def test_out_of_range_longitude_too_high():
    findings = validate_coordinates(0.0, 181.0)
    assert findings[0].code == FINDING_INVALID_RANGE


def test_out_of_range_longitude_too_low():
    findings = validate_coordinates(0.0, -181.0)
    assert findings[0].code == FINDING_INVALID_RANGE


def test_boundary_values_are_valid_not_invalid():
    findings = validate_coordinates(90.0, 180.0)
    assert findings[0].code == FINDING_VALID
    findings = validate_coordinates(-90.0, -180.0)
    assert findings[0].code == FINDING_VALID


def test_non_finite_nan():
    findings = validate_coordinates(math.nan, 0.0)
    assert findings[0].code == FINDING_NON_FINITE
    assert findings[0].is_error is True


def test_non_finite_infinity():
    findings = validate_coordinates(math.inf, 0.0)
    assert findings[0].code == FINDING_NON_FINITE
    findings = validate_coordinates(0.0, -math.inf)
    assert findings[0].code == FINDING_NON_FINITE


def test_unsupported_crs():
    findings = validate_coordinates(10.0, 10.0, coordinate_reference_system="UTM43N")
    assert findings[0].code == FINDING_UNSUPPORTED_CRS
    assert findings[0].is_error is True


def test_stale_source_timestamp_flagged():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = now - timedelta(days=10)
    findings = validate_coordinates(
        10.0, 10.0, location_uncertainty_m=5.0, location_source_observed_at=old, now=now, stale_after_seconds=86400,
    )
    codes = [f.code for f in findings]
    assert FINDING_STALE_SOURCE_TIMESTAMP in codes
    assert FINDING_VALID in codes  # staleness is informational, not disqualifying


def test_fresh_source_timestamp_not_flagged_stale():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    recent = now - timedelta(seconds=60)
    findings = validate_coordinates(
        10.0, 10.0, location_uncertainty_m=5.0, location_source_observed_at=recent, now=now, stale_after_seconds=86400,
    )
    codes = [f.code for f in findings]
    assert FINDING_STALE_SOURCE_TIMESTAMP not in codes


def test_classify_validation_status_missing_is_none():
    assert classify_validation_status(None, None) is None
    assert classify_validation_status(None, 10.0) is None


def test_classify_validation_status_valid():
    assert classify_validation_status(10.0, 10.0) == "valid"


def test_classify_validation_status_invalid_range():
    assert classify_validation_status(100.0, 10.0) == "invalid_range"


def test_classify_validation_status_non_finite():
    assert classify_validation_status(math.nan, 10.0) == "non_finite"


def test_classify_validation_status_unsupported_crs():
    assert classify_validation_status(10.0, 10.0, coordinate_reference_system="NAD83") == "unsupported_crs"


def test_is_usable_for_mapping_true_only_for_valid():
    assert is_usable_for_mapping(10.0, 10.0) is True
    assert is_usable_for_mapping(None, None) is False
    assert is_usable_for_mapping(999.0, 10.0) is False
    assert is_usable_for_mapping(10.0, 10.0, coordinate_reference_system="other") is False
