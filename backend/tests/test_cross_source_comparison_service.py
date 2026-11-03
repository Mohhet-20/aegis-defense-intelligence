"""Service-level tests for app/services/cross_source_comparison_service.py --
 comparison is a pure read, linking reuses
Evidence/EvidenceRelationship exactly, and nothing here ever merges two
observations into one authoritative value."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.evidence import Evidence
from app.models.observation import Observation
from app.models.sensor import Sensor
from app.services import cross_source_comparison_service as xsc


def _make_sensor(db, org, source, **overrides) -> Sensor:
    defaults = dict(organization_id=org.id, source_id=source.id, name="XSC Test Sensor", sensor_type="environmental", status="active")
    defaults.update(overrides)
    sensor = Sensor(**defaults)
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor


def _make_observation(db, org, sensor, source, *, observed_at, observation_type, value, unit) -> Observation:
    obs = Observation(
        organization_id=org.id, sensor_id=sensor.id, source_id=source.id, observed_at=observed_at,
        observation_type=observation_type, payload={}, measurement_value=value, unit=unit,
        validation_status="valid", data_origin="synthetic_demo",
    )
    db.add(obs)
    db.commit()
    db.refresh(obs)
    return obs


def test_compare_same_unit_within_tolerance(db, org, source):
    sensor_a = _make_sensor(db, org, source, name="Sensor A")
    sensor_b = _make_sensor(db, org, source, name="Sensor B")
    now = datetime.now(timezone.utc)
    obs_a = _make_observation(db, org, sensor_a, source, observed_at=now, observation_type="temperature_c", value=22.0, unit="celsius")
    obs_b = _make_observation(db, org, sensor_b, source, observed_at=now, observation_type="temperature_c", value=22.5, unit="celsius")

    result = xsc.compare(obs_a, obs_b, tolerance=1.0)
    assert result["same_measurement_type"] is True
    assert result["units_compatible"] is True
    assert result["delta"] == -0.5
    assert result["conflicting"] is False


def test_compare_different_units_converts_before_comparing(db, org, source):
    sensor_a = _make_sensor(db, org, source, name="Sensor A")
    sensor_b = _make_sensor(db, org, source, name="Sensor B")
    now = datetime.now(timezone.utc)
    obs_a = _make_observation(db, org, sensor_a, source, observed_at=now, observation_type="temperature_c", value=32.0, unit="fahrenheit")
    obs_b = _make_observation(db, org, sensor_b, source, observed_at=now, observation_type="temperature_c", value=0.0, unit="celsius")

    result = xsc.compare(obs_a, obs_b, tolerance=0.5)
    assert result["value_b_converted_to_unit_a"] is not None
    assert result["conflicting"] is False  # 32F == 0C exactly


def test_compare_incompatible_units_never_converts(db, org, source):
    sensor_a = _make_sensor(db, org, source, name="Sensor A")
    sensor_b = _make_sensor(db, org, source, name="Sensor B")
    now = datetime.now(timezone.utc)
    obs_a = _make_observation(db, org, sensor_a, source, observed_at=now, observation_type="temperature_c", value=22.0, unit="celsius")
    obs_b = _make_observation(db, org, sensor_b, source, observed_at=now, observation_type="temperature_c", value=5.0, unit="meters")

    result = xsc.compare(obs_a, obs_b, tolerance=1.0)
    assert result["units_compatible"] is False
    assert result["delta"] is None
    assert result["conflicting"] is None


def test_compare_without_tolerance_never_defaults_conflicting_to_false(db, org, source):
    sensor_a = _make_sensor(db, org, source, name="Sensor A")
    sensor_b = _make_sensor(db, org, source, name="Sensor B")
    now = datetime.now(timezone.utc)
    obs_a = _make_observation(db, org, sensor_a, source, observed_at=now, observation_type="temperature_c", value=22.0, unit="celsius")
    obs_b = _make_observation(db, org, sensor_b, source, observed_at=now, observation_type="temperature_c", value=99.0, unit="celsius")

    result = xsc.compare(obs_a, obs_b, tolerance=None)
    assert result["delta"] is not None
    assert result["conflicting"] is None  # "not assessed," never a false "they agree"


def test_compare_missing_value_reports_missing_not_zero(db, org, source):
    sensor_a = _make_sensor(db, org, source, name="Sensor A")
    sensor_b = _make_sensor(db, org, source, name="Sensor B")
    now = datetime.now(timezone.utc)
    obs_a = _make_observation(db, org, sensor_a, source, observed_at=now, observation_type="detection_summary", value=None, unit=None)
    obs_b = _make_observation(db, org, sensor_b, source, observed_at=now, observation_type="detection_summary", value=None, unit=None)

    result = xsc.compare(obs_a, obs_b, tolerance=1.0)
    assert result["missing_a"] is True
    assert result["missing_b"] is True
    assert result["value_a"] is None  # never fabricated as 0.0


def test_create_comparison_link_reuses_existing_evidence_wrapper(db, org, source):
    sensor_a = _make_sensor(db, org, source, name="Sensor A")
    sensor_b = _make_sensor(db, org, source, name="Sensor B")
    now = datetime.now(timezone.utc)
    obs_a = _make_observation(db, org, sensor_a, source, observed_at=now, observation_type="temperature_c", value=22.0, unit="celsius")
    obs_b = _make_observation(db, org, sensor_b, source, observed_at=now, observation_type="temperature_c", value=22.5, unit="celsius")
    comparison = xsc.compare(obs_a, obs_b, tolerance=1.0)

    relationship, created = xsc.create_comparison_link(db, org.id, obs_a, obs_b, comparison=comparison)
    assert created is True
    assert relationship.relationship_type == "cross_source_comparison"

    # A second link request for the SAME pair is idempotent -- no
    # duplicate Evidence wrapper, no duplicate relationship.
    relationship2, created2 = xsc.create_comparison_link(db, org.id, obs_a, obs_b, comparison=comparison)
    assert created2 is False
    assert relationship2.id == relationship.id
    assert db.query(Evidence).filter_by(organization_id=org.id, evidence_type="sensor_observation").count() == 2


def test_create_comparison_link_rejects_self_comparison(db, org, source):
    sensor_a = _make_sensor(db, org, source, name="Sensor A")
    now = datetime.now(timezone.utc)
    obs_a = _make_observation(db, org, sensor_a, source, observed_at=now, observation_type="temperature_c", value=22.0, unit="celsius")
    comparison = xsc.compare(obs_a, obs_a, tolerance=1.0)

    import pytest

    with pytest.raises(xsc.IncomparableObservationsError):
        xsc.create_comparison_link(db, org.id, obs_a, obs_a, comparison=comparison)


def test_find_candidate_observations_filters_by_window_and_type(db, org, source):
    sensor_a = _make_sensor(db, org, source, name="Sensor A")
    sensor_b = _make_sensor(db, org, source, name="Sensor B")
    now = datetime.now(timezone.utc)
    _make_observation(db, org, sensor_a, source, observed_at=now, observation_type="temperature_c", value=22.0, unit="celsius")
    _make_observation(db, org, sensor_b, source, observed_at=now - timedelta(days=10), observation_type="temperature_c", value=22.0, unit="celsius")

    candidates = xsc.find_candidate_observations(
        db, org.id, sensor_ids=[sensor_a.id, sensor_b.id], measurement_type="temperature_c",
        since=now - timedelta(hours=1), until=now + timedelta(hours=1),
    )
    assert len(candidates) == 1  # the 10-days-ago one falls outside the window
