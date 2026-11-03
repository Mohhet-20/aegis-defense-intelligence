"""API tests for /sensor-ingestion -- synthetic
and file batch submission, job listing/retry, and the
OBSERVATION_INGEST vs OBSERVATION_READ permission split."""
from __future__ import annotations

import io

from app.models.sensor import Sensor


def _make_sensor(db, org, source, **overrides) -> Sensor:
    defaults = dict(
        organization_id=org.id, source_id=source.id, name="API Ingestion Sensor", sensor_type="environmental",
        status="active", lifecycle_status="registered", measurement_types=["temperature_c"],
        measurement_units={"temperature_c": "celsius"}, operating_range={"temperature_c": {"min": -10.0, "max": 45.0}},
    )
    defaults.update(overrides)
    sensor = Sensor(**defaults)
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor


def test_submit_synthetic_batch_as_analyst(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    response = client.post(
        "/api/v1/sensor-ingestion/synthetic-batches",
        json={"source_id": source.id, "sensor_id": sensor.id, "measurement_type": "temperature_c", "unit": "celsius", "count": 10, "seed": 1},
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["accepted_count"] == 10
    assert body["job_type"] == "sensor_synthetic"


def test_submit_synthetic_batch_viewer_forbidden(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    response = client.post(
        "/api/v1/sensor-ingestion/synthetic-batches",
        json={"source_id": source.id, "sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 5, "seed": 2},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 403


def test_submit_synthetic_batch_investigator_forbidden(client, tokens, auth_header, db, org, source):
    """Investigator can review anomalies but not submit new batches --
    mirrors the TRACKING_RUN split."""
    sensor = _make_sensor(db, org, source)
    response = client.post(
        "/api/v1/sensor-ingestion/synthetic-batches",
        json={"source_id": source.id, "sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 5, "seed": 3},
        headers=auth_header(tokens, "investigator"),
    )
    assert response.status_code == 403


def test_submit_synthetic_batch_unknown_source_404(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    response = client.post(
        "/api/v1/sensor-ingestion/synthetic-batches",
        json={"source_id": "does-not-exist", "sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 5, "seed": 4},
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 404


def test_submit_json_file_batch(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    import json as _json
    from datetime import datetime, timezone

    records = [{"sensor_id": sensor.id, "measurement_type": "temperature_c", "value": 21.0, "unit": "celsius", "observed_at": datetime.now(timezone.utc).isoformat(), "external_id": "api-json-1"}]
    content = _json.dumps(records).encode()
    response = client.post(
        "/api/v1/sensor-ingestion/batches",
        data={"source_id": source.id, "format": "json"},
        files={"file": ("batch.json", io.BytesIO(content), "application/json")},
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 201, response.text
    assert response.json()["accepted_count"] == 1


def test_submit_file_batch_bad_format_rejected(client, tokens, auth_header, db, org, source):
    response = client.post(
        "/api/v1/sensor-ingestion/batches",
        data={"source_id": source.id, "format": "xml"},
        files={"file": ("batch.xml", io.BytesIO(b"<x/>"), "application/xml")},
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 400


def test_list_and_get_sensor_batches(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    submit = client.post(
        "/api/v1/sensor-ingestion/synthetic-batches",
        json={"source_id": source.id, "sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 3, "seed": 5},
        headers=auth_header(tokens, "analyst"),
    )
    job_id = submit.json()["id"]

    list_response = client.get("/api/v1/sensor-ingestion/batches", headers=auth_header(tokens, "viewer"))
    assert list_response.status_code == 200
    assert any(j["id"] == job_id for j in list_response.json()["items"])

    get_response = client.get(f"/api/v1/sensor-ingestion/batches/{job_id}", headers=auth_header(tokens, "viewer"))
    assert get_response.status_code == 200
    assert get_response.json()["id"] == job_id


def test_list_batch_records(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    submit = client.post(
        "/api/v1/sensor-ingestion/synthetic-batches",
        json={"source_id": source.id, "sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 3, "seed": 6},
        headers=auth_header(tokens, "analyst"),
    )
    job_id = submit.json()["id"]
    response = client.get(f"/api/v1/sensor-ingestion/batches/{job_id}/records", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 200
    assert len(response.json()["items"]) == 3


def test_retry_only_allowed_for_failed_jobs(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    submit = client.post(
        "/api/v1/sensor-ingestion/synthetic-batches",
        json={"source_id": source.id, "sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 3, "seed": 7},
        headers=auth_header(tokens, "analyst"),
    )
    job_id = submit.json()["id"]
    assert submit.json()["status"] == "completed"
    retry_response = client.post(f"/api/v1/sensor-ingestion/batches/{job_id}/retry", headers=auth_header(tokens, "analyst"))
    assert retry_response.status_code == 400


def test_retry_completed_with_errors_synthetic_job_succeeds(client, tokens, auth_header, db, org, source):
    """A config-validation failure (e.g. missing measurement_type) marks
    the job "failed" WITHOUT preserving synthetic_config in provenance
    -- by design, there is nothing useful to retry. The genuinely
    retryable "failed"/"completed_with_errors" path is a batch that
    reached the real connector but had every record rejected (here: a
    unit incompatible with the sensor's configured unit) -- that DOES
    preserve synthetic_config, since it goes through the success path
    of submit_synthetic_batch()."""
    sensor = _make_sensor(db, org, source)
    submit = client.post(
        "/api/v1/sensor-ingestion/synthetic-batches",
        json={"source_id": source.id, "sensor_id": sensor.id, "measurement_type": "temperature_c", "unit": "meters", "count": 3, "seed": 8},
        headers=auth_header(tokens, "analyst"),
    )
    assert submit.status_code == 201, submit.text
    job_id = submit.json()["id"]
    assert submit.json()["status"] == "completed_with_errors"
    assert submit.json()["rejected_count"] == 3

    retry_response = client.post(f"/api/v1/sensor-ingestion/batches/{job_id}/retry", headers=auth_header(tokens, "analyst"))
    assert retry_response.status_code == 201, retry_response.text
    assert retry_response.json()["retry_count"] == 1


def test_retry_config_validation_failure_is_not_retryable(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    submit = client.post(
        "/api/v1/sensor-ingestion/synthetic-batches",
        json={"source_id": source.id, "sensor_id": sensor.id, "measurement_type": "", "count": 3, "seed": 9},
        headers=auth_header(tokens, "analyst"),
    )
    job_id = submit.json()["id"]
    assert submit.json()["status"] == "failed"
    retry_response = client.post(f"/api/v1/sensor-ingestion/batches/{job_id}/retry", headers=auth_header(tokens, "analyst"))
    assert retry_response.status_code == 400


def test_sensor_batch_not_found(client, tokens, auth_header):
    response = client.get("/api/v1/sensor-ingestion/batches/does-not-exist", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 404
