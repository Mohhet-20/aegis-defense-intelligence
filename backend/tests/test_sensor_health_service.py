"""Service-level tests for app/services/sensor_health_service.py --
 four separate health signals computed on
demand, and the explicit/audited lifecycle_status recompute."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.audit import AuditRecord
from app.models.sensor import Sensor
from app.services import anomaly_service, sensor_health_service, sensor_ingestion_service as ingest_svc


def _make_sensor(db, org, source, **overrides) -> Sensor:
    defaults = dict(
        organization_id=org.id, source_id=source.id, name="Health Test Sensor", sensor_type="environmental",
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


def test_never_connected_sensor_health(db, org, source):
    sensor = _make_sensor(db, org, source)
    health = sensor_health_service.compute_health(db, org.id, sensor)
    assert health.connectivity.status == "never_connected"
    assert health.measurement_quality.status == "insufficient_data"
    assert health.anomaly_status.unresolved_count == 0
    assert health.device_reported.status is None


def test_connected_sensor_after_real_ingestion(db, org, source):
    sensor = _make_sensor(db, org, source)
    ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={"sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 5, "seed": 30, "start_at": datetime.now(timezone.utc).isoformat()},
    )
    db.refresh(sensor)
    health = sensor_health_service.compute_health(db, org.id, sensor)
    assert health.connectivity.status == "connected"
    assert health.measurement_quality.status == "good"
    assert health.measurement_quality.sample_size == 5


def test_offline_sensor_detected_after_long_silence(db, org, source):
    old = datetime.now(timezone.utc) - timedelta(days=2)
    sensor = _make_sensor(db, org, source, last_seen_at=old, lifecycle_status="active")
    db.commit()
    db.refresh(sensor)
    health = sensor_health_service.compute_health(db, org.id, sensor)
    assert health.connectivity.status == "offline"


def test_device_reported_status_surfaced_verbatim(db, org, source):
    now = datetime.now(timezone.utc)
    sensor = _make_sensor(db, org, source, device_reported_status="low_battery", device_reported_status_at=now)
    health = sensor_health_service.compute_health(db, org.id, sensor)
    assert health.device_reported.status == "low_battery"
    assert health.device_reported.as_of == now


def test_recompute_lifecycle_status_registered_to_active_on_valid_observation(db, org, source):
    sensor = _make_sensor(db, org, source)
    ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={"sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 5, "seed": 31, "start_at": datetime.now(timezone.utc).isoformat()},
    )
    db.refresh(sensor)
    updated, health = sensor_health_service.recompute_lifecycle_status(db, org.id, sensor, actor_user_id=None)
    assert updated.lifecycle_status == "active"


def test_recompute_lifecycle_status_to_degraded_on_unresolved_anomaly(db, org, source):
    sensor = _make_sensor(db, org, source)
    ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={
            "sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 10, "seed": 32,
            "value_overrides": {"9": 99.0}, "start_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.refresh(sensor)
    anomaly_service.run_checks(db, organization_id=org.id, sensor=sensor, measurement_type="temperature_c")
    updated, health = sensor_health_service.recompute_lifecycle_status(db, org.id, sensor, actor_user_id=None)
    assert updated.lifecycle_status == "degraded"
    assert health.anomaly_status.unresolved_count > 0


def test_recompute_lifecycle_status_never_overrides_maintenance(db, org, source):
    sensor = _make_sensor(db, org, source, lifecycle_status="maintenance")
    updated, _ = sensor_health_service.recompute_lifecycle_status(db, org.id, sensor, actor_user_id=None)
    assert updated.lifecycle_status == "maintenance"


def test_recompute_lifecycle_status_never_overrides_retired(db, org, source):
    sensor = _make_sensor(db, org, source, lifecycle_status="retired")
    updated, _ = sensor_health_service.recompute_lifecycle_status(db, org.id, sensor, actor_user_id=None)
    assert updated.lifecycle_status == "retired"


def test_recompute_lifecycle_status_writes_audit_record_on_change(db, org, source, seeded_users):
    """The registered->active transition happens automatically inside
    the ingestion pipeline itself (sensor_ingestion_service.py), so by
    the time recompute_lifecycle_status() runs, the sensor is already
    "active" and there is nothing new to recompute -- this test
    exercises a transition recompute_lifecycle_status() genuinely
    controls: active -> degraded once an unresolved anomaly exists."""
    sensor = _make_sensor(db, org, source)
    ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={
            "sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 10, "seed": 33,
            "value_overrides": {"9": 99.0}, "start_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.refresh(sensor)
    assert sensor.lifecycle_status == "active"  # set automatically by ingestion
    anomaly_service.run_checks(db, organization_id=org.id, sensor=sensor, measurement_type="temperature_c")

    actor = seeded_users["analyst"]
    sensor_health_service.recompute_lifecycle_status(db, org.id, sensor, actor_user_id=actor.id)
    logs = db.query(AuditRecord).filter_by(action="sensor.lifecycle_status_recomputed", target_id=sensor.id).all()
    assert len(logs) == 1
    assert logs[0].context_metadata["previous_status"] == "active"
    assert logs[0].context_metadata["new_status"] == "degraded"
    assert logs[0].actor_user_id == actor.id


def test_recompute_lifecycle_status_is_noop_when_status_unchanged(db, org, source):
    sensor = _make_sensor(db, org, source, lifecycle_status="active", last_seen_at=datetime.now(timezone.utc))
    db.commit()
    db.refresh(sensor)
    sensor_health_service.recompute_lifecycle_status(db, org.id, sensor, actor_user_id=None)
    logs = db.query(AuditRecord).filter_by(action="sensor.lifecycle_status_recomputed", target_id=sensor.id).all()
    assert len(logs) == 0
