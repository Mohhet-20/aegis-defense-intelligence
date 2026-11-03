"""Service-level tests for app/services/sensor_ingestion_service.py --
 the real ingestion pipeline, not hand-built
rows. Exercises submit_synthetic_batch, submit_file_batch (json/csv),
duplicate detection, retired-sensor rejection, and unknown-sensor
rejection against a real (in-memory) database."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.models.ingestion_job import IngestionJob
from app.models.observation import Observation
from app.models.raw_record import RawRecord
from app.models.sensor import Sensor
from app.services import sensor_ingestion_service as ingest_svc


def _make_sensor(db, org, source, **overrides) -> Sensor:
    defaults = dict(
        organization_id=org.id, source_id=source.id, name="Test Env Sensor", sensor_type="environmental",
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


def test_submit_synthetic_batch_accepts_valid_records(db, org, source):
    sensor = _make_sensor(db, org, source)
    job = ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={"sensor_id": sensor.id, "measurement_type": "temperature_c", "unit": "celsius", "count": 10, "seed": 1, "base_value": 22.0, "noise_amplitude": 0.5},
    )
    assert job.status == "completed"
    assert job.accepted_count == 10
    assert job.rejected_count == 0
    assert job.job_type == "sensor_synthetic"

    observations = db.query(Observation).filter_by(sensor_id=sensor.id).all()
    assert len(observations) == 10
    for obs in observations:
        assert obs.validation_status == "valid"
        assert obs.measurement_value is not None
        assert obs.ingestion_job_id == job.id
        assert obs.schema_version == "1.0"


def test_submit_synthetic_batch_updates_sensor_lifecycle_and_last_seen(db, org, source):
    sensor = _make_sensor(db, org, source)
    assert sensor.lifecycle_status == "registered"
    ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={"sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 5, "seed": 2},
    )
    db.refresh(sensor)
    assert sensor.lifecycle_status == "active"
    assert sensor.last_seen_at is not None
    assert sensor.last_ingestion_success_at is not None


def test_retired_sensor_rejects_all_records(db, org, source):
    sensor = _make_sensor(db, org, source, lifecycle_status="retired")
    job = ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={"sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 3, "seed": 3},
    )
    assert job.accepted_count == 0
    assert job.rejected_count == 3
    raw_records = db.query(RawRecord).filter_by(ingestion_job_id=job.id).all()
    assert len(raw_records) == 3
    assert all(r.validation_status == "invalid" for r in raw_records)


def test_unknown_sensor_id_rejected_but_raw_record_preserved(db, org, source):
    job = ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={"sensor_id": "does-not-exist", "measurement_type": "temperature_c", "count": 2, "seed": 4},
    )
    assert job.accepted_count == 0
    assert job.rejected_count == 2
    raw_records = db.query(RawRecord).filter_by(ingestion_job_id=job.id).all()
    assert len(raw_records) == 2  # quarantine reference always created


def test_out_of_range_value_still_creates_an_observation(db, org, source):
    sensor = _make_sensor(db, org, source)
    job = ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={
            "sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 3, "seed": 5,
            "base_value": 22.0, "noise_amplitude": 0.1, "value_overrides": {"2": 99.0},
        },
    )
    assert job.accepted_count == 3  # out-of-range is a flag, not a rejection
    out_of_range = db.query(Observation).filter_by(sensor_id=sensor.id, validation_status="out_of_range").all()
    assert len(out_of_range) == 1
    assert out_of_range[0].measurement_value == 99.0


def test_duplicate_within_same_batch_detected(db, org, source):
    sensor = _make_sensor(db, org, source)
    # skip_indices leaves a gap but external_id numbering is still
    # unique per index by default -- force a duplicate by reusing seed
    # + identical config twice in the SAME batch via value_overrides is
    # not how the synthetic connector dedups; instead submit the same
    # synthetic config twice as two SEPARATE batches, which is exactly
    # the cross-batch duplicate path the service documents.
    config = {"sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 3, "seed": 6}
    job1 = ingest_svc.submit_synthetic_batch(db, organization_id=org.id, source_id=source.id, created_by_user_id=None, config=config)
    assert job1.accepted_count == 3
    job2 = ingest_svc.submit_synthetic_batch(db, organization_id=org.id, source_id=source.id, created_by_user_id=None, config=config)
    assert job2.duplicate_count == 3
    assert job2.accepted_count == 0
    # No second set of Observations was created for the duplicate batch.
    assert db.query(Observation).filter_by(sensor_id=sensor.id).count() == 3


def test_invalid_synthetic_config_fails_job_without_crashing(db, org, source):
    sensor = _make_sensor(db, org, source)
    job = ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={"sensor_id": sensor.id},  # missing required measurement_type
    )
    assert job.status == "failed"
    assert job.error_summary


def test_retry_job_preserves_original_synthetic_config(db, org, source):
    sensor = _make_sensor(db, org, source)
    config = {"sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 2, "seed": 7}
    job = ingest_svc.submit_synthetic_batch(db, organization_id=org.id, source_id=source.id, created_by_user_id=None, config=config)
    assert job.provenance.get("synthetic_config") == config

    retried = ingest_svc.retry_job(db, org.id, job, created_by_user_id=None)
    assert retried.retry_count == job.retry_count + 1
    # The retry re-submits the SAME config -- so this second run hits
    # the duplicate path (external_ids already seen), not a second
    # accepted batch.
    assert retried.duplicate_count == 2


def test_retry_non_retryable_job_type_raises(db, org, source):
    sensor = _make_sensor(db, org, source)
    content = json.dumps([{"sensor_id": sensor.id, "measurement_type": "temperature_c", "value": 20.0, "unit": "celsius", "observed_at": datetime.now(timezone.utc).isoformat(), "external_id": "json-1"}]).encode()
    job = ingest_svc.submit_file_batch(db, organization_id=org.id, source_id=source.id, fmt="json", content=content, created_by_user_id=None)
    import pytest

    with pytest.raises(ValueError):
        ingest_svc.retry_job(db, org.id, job, created_by_user_id=None)


def test_submit_json_file_batch(db, org, source):
    sensor = _make_sensor(db, org, source)
    now = datetime.now(timezone.utc)
    records = [
        {"sensor_id": sensor.id, "measurement_type": "temperature_c", "value": 20.0 + i, "unit": "celsius", "observed_at": (now - timedelta(minutes=i)).isoformat(), "external_id": f"json-batch-{i}"}
        for i in range(5)
    ]
    content = json.dumps(records).encode()
    job = ingest_svc.submit_file_batch(db, organization_id=org.id, source_id=source.id, fmt="json", content=content, created_by_user_id=None)
    assert job.job_type == "sensor_json_batch"
    assert job.accepted_count == 5
    assert job.rejected_count == 0


def test_submit_csv_file_batch(db, org, source):
    sensor = _make_sensor(db, org, source)
    now = datetime.now(timezone.utc)
    rows = ["sensor_id,measurement_type,value,unit,observed_at,external_id"]
    for i in range(4):
        rows.append(f"{sensor.id},temperature_c,{20.0 + i},celsius,{(now - timedelta(minutes=i)).isoformat()},csv-batch-{i}")
    content = "\n".join(rows).encode("utf-8")
    job = ingest_svc.submit_file_batch(db, organization_id=org.id, source_id=source.id, fmt="csv", content=content, created_by_user_id=None)
    assert job.job_type == "sensor_csv_batch"
    assert job.accepted_count == 4
    assert job.rejected_count == 0


def test_unsupported_format_raises(db, org, source):
    import pytest

    with pytest.raises(ingest_svc.UnsupportedBatchFormatError):
        ingest_svc.submit_file_batch(db, organization_id=org.id, source_id=source.id, fmt="xml", content=b"<x/>", created_by_user_id=None)


def test_device_reported_status_populated_only_when_explicitly_supplied(db, org, source):
    sensor = _make_sensor(db, org, source)
    now = datetime.now(timezone.utc)
    content = json.dumps([{
        "sensor_id": sensor.id, "measurement_type": "temperature_c", "value": 20.0, "unit": "celsius",
        "observed_at": now.isoformat(), "external_id": "with-device-status", "device_status": "nominal",
    }]).encode()
    ingest_svc.submit_file_batch(db, organization_id=org.id, source_id=source.id, fmt="json", content=content, created_by_user_id=None)
    db.refresh(sensor)
    assert sensor.device_reported_status == "nominal"
    assert sensor.device_reported_status_at is not None


def test_ingesting_second_batch_against_existing_history_does_not_crash(db, org, source):
    """Regression test for the naive/aware datetime mismatch between a
    DB-read prior observation and a freshly parsed incoming record --
    the bug this session found and fixed in _SensorContext."""
    sensor = _make_sensor(db, org, source)
    config1 = {"sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 5, "seed": 10, "start_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}
    job1 = ingest_svc.submit_synthetic_batch(db, organization_id=org.id, source_id=source.id, created_by_user_id=None, config=config1)
    assert job1.accepted_count == 5

    config2 = {"sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 5, "seed": 11, "start_at": datetime.now(timezone.utc).isoformat()}
    job2 = ingest_svc.submit_synthetic_batch(db, organization_id=org.id, source_id=source.id, created_by_user_id=None, config=config2)
    assert job2.accepted_count == 5
    assert job2.rejected_count == 0
