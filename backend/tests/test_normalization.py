"""Normalization + validation engine tests (Sections 5 & 9).
Exercises the pure functions directly -- no database, no HTTP.
"""
from __future__ import annotations

from app.services import normalization_service as norm
from app.services import validation_service as vs


# --- timestamps -------------------------------------------------------


def test_timestamp_with_explicit_offset_is_parsed_aware():
    result = norm.normalize_timestamp("2026-01-01T00:00:00+05:00")
    assert result.policy == "parsed_aware"
    assert result.value.utcoffset().total_seconds() == 0  # converted to UTC
    assert result.value.hour == 19  # 00:00 +05:00 -> 19:00 UTC the prior day... actually just check tzinfo


def test_naive_timestamp_is_assumed_utc_not_silently_dropped():
    result = norm.normalize_timestamp("2026-01-01T00:00:00")
    assert result.policy == "assumed_utc"
    assert result.value is not None
    assert result.value.tzinfo is not None


def test_unparseable_timestamp_is_reported_not_guessed():
    result = norm.normalize_timestamp("definitely not a date")
    assert result.value is None
    assert result.policy == "unparseable"


def test_missing_timestamp_is_unparseable_not_defaulted_to_now():
    result = norm.normalize_timestamp(None)
    assert result.value is None


def test_epoch_seconds_timestamp_is_parsed_aware():
    result = norm.normalize_timestamp(1767225600)
    assert result.value is not None
    assert result.policy == "parsed_aware"


# --- coordinates --------------------------------------------------------


def test_missing_coordinates_stay_missing_never_defaulted_to_zero():
    lat, lon = norm.normalize_coordinates(None, None)
    assert (lat, lon) == (None, None)


def test_partial_coordinate_pair_is_treated_as_missing():
    lat, lon = norm.normalize_coordinates(38.9, None)
    assert (lat, lon) == (None, None)


def test_valid_coordinates_pass_through():
    lat, lon = norm.normalize_coordinates("38.9", "-77.0")
    assert lat == 38.9 and lon == -77.0


def test_out_of_range_coordinate_raises():
    import pytest

    with pytest.raises(ValueError, match="out of range"):
        norm.normalize_coordinates(999.0, 0.0)


# --- severity -> priority -----------------------------------------------


def test_known_severity_maps_to_documented_priority():
    priority, recognized = norm.map_severity_to_priority("critical")
    assert priority == "critical"
    assert recognized is True


def test_unknown_severity_is_unmapped_not_escalated():
    priority, recognized = norm.map_severity_to_priority("bananas")
    assert priority is None  # never silently escalated to a guessed priority
    assert recognized is False


def test_absent_severity_is_recognized_as_absent():
    priority, recognized = norm.map_severity_to_priority(None)
    assert priority is None
    assert recognized is True  # no warning warranted for a simply-absent field


def test_severity_mapping_is_case_insensitive():
    priority, recognized = norm.map_severity_to_priority("HIGH")
    assert priority == "high"
    assert recognized is True


# --- event type -----------------------------------------------------------


def test_known_event_type_is_classified():
    assert norm.classify_event_type("perimeter_motion") is True


def test_unknown_event_type_is_not_classified_but_not_an_error():
    assert norm.classify_event_type("brand_new_sensor_category") is False


# --- content fingerprint ---------------------------------------------------


def test_content_fingerprint_is_order_independent():
    a = norm.content_fingerprint({"x": 1, "y": 2})
    b = norm.content_fingerprint({"y": 2, "x": 1})
    assert a == b


def test_content_fingerprint_differs_for_different_content():
    a = norm.content_fingerprint({"x": 1})
    b = norm.content_fingerprint({"x": 2})
    assert a != b


# --- the validation engine --------------------------------------------------


def test_valid_record_has_no_errors():
    record = {"event_type": "perimeter_motion", "title": "x", "observed_at": "2026-01-01T00:00:00Z"}
    outcome = vs.validate_record(record)
    assert outcome.is_valid
    assert outcome.errors == []


def test_each_missing_required_field_is_its_own_error():
    outcome = vs.validate_record({})
    codes = [e.code for e in outcome.errors]
    assert codes.count(vs.ERR_MISSING_REQUIRED_FIELD) == 3  # event_type, title, observed_at


def test_oversized_field_is_rejected():
    record = {"event_type": "x", "title": "y", "observed_at": "2026-01-01T00:00:00Z", "description": "a" * (vs.MAX_FIELD_LENGTH + 1)}
    outcome = vs.validate_record(record)
    assert not outcome.is_valid
    assert any(e.code == vs.ERR_OVERSIZED_FIELD for e in outcome.errors)


def test_too_many_fields_is_rejected():
    record = {f"field_{i}": i for i in range(vs.MAX_ATTRIBUTE_COUNT + 1)}
    record.update({"event_type": "x", "title": "y", "observed_at": "2026-01-01T00:00:00Z"})
    outcome = vs.validate_record(record)
    assert any(e.code == vs.ERR_TOO_MANY_ATTRIBUTES for e in outcome.errors)


def test_non_dict_record_is_malformed_not_a_crash():
    outcome = vs.validate_record("not a record")
    assert not outcome.is_valid
    assert outcome.errors[0].code == vs.ERR_MALFORMED_RECORD


def test_rule_version_is_stamped_on_every_outcome():
    outcome = vs.validate_record({"event_type": "x", "title": "y", "observed_at": "2026-01-01T00:00:00Z"})
    assert outcome.rule_version == vs.RULE_VERSION
