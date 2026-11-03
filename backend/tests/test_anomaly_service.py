"""Service-level tests for app/services/anomaly_service.py (Phase 6,
Section 9) -- runs real checks against real ingested Observation
history and verifies idempotent persistence + the analyst review
workflow's category mapping."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.observation_anomaly import ObservationAnomaly
from app.models.sensor import Sensor
from app.services import anomaly_service, sensor_ingestion_service as ingest_svc


def _make_sensor(db, org, source, **overrides) -> Sensor:
    defaults = dict(
        organization_id=org.id, source_id=source.id, name="Anomaly Test Sensor", sensor_type="environmental",
        status="active", lifecycle_status="registered",
        measurement_types=["temperature_c"], measurement_units={"temperature_c": "celsius"},
        operating_range={"temperature_c": {"min": -10.0, "max": 45.0}}, nominal_sampling_interval_seconds=60.0,
    )
    defaults.update(overrides)
    sensor = Sensor(**defaults)
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor


def _ingest_series(db, org, source, sensor, *, count, seed, base_value=22.0, noise_amplitude=0.3, value_overrides=None, start_at=None):
    config = {
        "sensor_id": sensor.id, "measurement_type": "temperature_c", "unit": "celsius",
        "count": count, "seed": seed, "base_value": base_value, "noise_amplitude": noise_amplitude,
        "interval_seconds": 60.0,
    }
    if value_overrides:
        config["value_overrides"] = value_overrides
    if start_at:
        config["start_at"] = start_at
    return ingest_svc.submit_synthetic_batch(db, organization_id=org.id, source_id=source.id, created_by_user_id=None, config=config)


def test_run_checks_detects_range_violation_against_real_series(db, org, source):
    sensor = _make_sensor(db, org, source)
    _ingest_series(db, org, source, sensor, count=10, seed=20, value_overrides={"9": 99.0})
    db.refresh(sensor)
    result = anomaly_service.run_checks(db, organization_id=org.id, sensor=sensor, measurement_type="temperature_c")
    methods = {a.detection_method for a in result["created"]}
    assert "range_violation" in methods
    for anomaly in result["created"]:
        assert anomaly.category == "statistical_deviation"
        assert anomaly.review_status == "unreviewed"


def test_run_checks_is_idempotent_for_same_observation(db, org, source):
    sensor = _make_sensor(db, org, source)
    _ingest_series(db, org, source, sensor, count=10, seed=21, value_overrides={"9": 99.0})
    db.refresh(sensor)
    first = anomaly_service.run_checks(db, organization_id=org.id, sensor=sensor, measurement_type="temperature_c")
    first_count = len(first["created"])
    assert first_count > 0

    second = anomaly_service.run_checks(db, organization_id=org.id, sensor=sensor, measurement_type="temperature_c")
    assert len(second["created"]) == 0
    assert len(second["already_known"]) == first_count


def test_run_checks_insufficient_baseline_reported_for_short_series(db, org, source):
    sensor = _make_sensor(db, org, source)
    _ingest_series(db, org, source, sensor, count=2, seed=22)
    db.refresh(sensor)
    result = anomaly_service.run_checks(db, organization_id=org.id, sensor=sensor, measurement_type="temperature_c")
    assert result["insufficient_baseline"]  # non-empty dict -- never silently skipped


def test_run_checks_no_history_only_checks_heartbeat(db, org, source):
    sensor = _make_sensor(db, org, source)
    result = anomaly_service.run_checks(db, organization_id=org.id, sensor=sensor, measurement_type="temperature_c")
    # No observations at all -- only the "never connected" heartbeat
    # candidate can fire; never crashes on an empty history.
    assert isinstance(result["created"], list)


def test_review_anomaly_confirmed_unusual_sets_analyst_confirmed_category(db, org, source, seeded_users):
    sensor = _make_sensor(db, org, source)
    _ingest_series(db, org, source, sensor, count=10, seed=23, value_overrides={"9": 99.0})
    db.refresh(sensor)
    result = anomaly_service.run_checks(db, organization_id=org.id, sensor=sensor, measurement_type="temperature_c")
    anomaly = result["created"][0]
    assert anomaly.category != "analyst_confirmed"  # never set by a detection method itself

    reviewer = seeded_users["analyst"]
    reviewed = anomaly_service.review_anomaly(db, anomaly, reviewer_user_id=reviewer.id, review_status="confirmed_unusual", review_note="looked at it")
    assert reviewed.category == "analyst_confirmed"
    assert reviewed.reviewed_by_user_id == reviewer.id
    assert reviewed.review_note == "looked at it"


def test_review_anomaly_data_quality_issue_sets_data_quality_category(db, org, source, seeded_users):
    sensor = _make_sensor(db, org, source)
    _ingest_series(db, org, source, sensor, count=10, seed=24, value_overrides={"9": 99.0})
    db.refresh(sensor)
    result = anomaly_service.run_checks(db, organization_id=org.id, sensor=sensor, measurement_type="temperature_c")
    anomaly = result["created"][0]
    reviewer = seeded_users["analyst"]
    reviewed = anomaly_service.review_anomaly(db, anomaly, reviewer_user_id=reviewer.id, review_status="data_quality_issue", review_note=None)
    assert reviewed.category == "data_quality"


def test_review_anomaly_rejects_invalid_review_status(db, org, source, seeded_users):
    sensor = _make_sensor(db, org, source)
    _ingest_series(db, org, source, sensor, count=10, seed=25, value_overrides={"9": 99.0})
    db.refresh(sensor)
    result = anomaly_service.run_checks(db, organization_id=org.id, sensor=sensor, measurement_type="temperature_c")
    anomaly = result["created"][0]
    import pytest

    with pytest.raises(ValueError):
        anomaly_service.review_anomaly(db, anomaly, reviewer_user_id=seeded_users["analyst"].id, review_status="not_a_real_status", review_note=None)


def test_list_anomalies_query_filters_by_sensor_and_review_status(db, org, source):
    sensor_a = _make_sensor(db, org, source, name="Sensor A")
    sensor_b = _make_sensor(db, org, source, name="Sensor B")
    _ingest_series(db, org, source, sensor_a, count=10, seed=26, value_overrides={"9": 99.0})
    _ingest_series(db, org, source, sensor_b, count=10, seed=27, value_overrides={"9": 99.0})
    db.refresh(sensor_a)
    db.refresh(sensor_b)
    anomaly_service.run_checks(db, organization_id=org.id, sensor=sensor_a, measurement_type="temperature_c")
    anomaly_service.run_checks(db, organization_id=org.id, sensor=sensor_b, measurement_type="temperature_c")

    stmt = anomaly_service.list_anomalies_query(org.id, sensor_id=sensor_a.id)
    rows = db.execute(stmt).scalars().all()
    assert all(r.sensor_id == sensor_a.id for r in rows)
    assert len(rows) > 0

    stmt_unreviewed = anomaly_service.list_anomalies_query(org.id, review_status="unreviewed")
    rows_unreviewed = db.execute(stmt_unreviewed).scalars().all()
    assert len(rows_unreviewed) >= len(rows)
