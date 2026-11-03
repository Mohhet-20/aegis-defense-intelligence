"""API tests for /sensor-analytics --
timeseries, statistics, health, anomaly run/list/review, and the
ANOMALY_READ vs ANOMALY_REVIEW permission split."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.sensor import Sensor


def _make_sensor(db, org, source, **overrides) -> Sensor:
    defaults = dict(
        organization_id=org.id, source_id=source.id, name="Analytics API Sensor", sensor_type="environmental",
        status="active", lifecycle_status="registered", measurement_types=["temperature_c"],
        measurement_units={"temperature_c": "celsius"}, operating_range={"temperature_c": {"min": -10.0, "max": 45.0}},
        nominal_sampling_interval_seconds=60.0,
    )
    defaults.update(overrides)
    sensor = Sensor(**defaults)
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor


def _ingest(client, tokens, auth_header, source, sensor, *, count, seed, value_overrides=None):
    # start_at is chosen so the LAST point lands at ~now (interval_seconds
    # defaults to 60s) -- a series ending an hour ago would otherwise
    # trip the sensor's own missed-heartbeat threshold, which is a
    # separate, correct health signal this test isn't exercising.
    start_at = datetime.now(timezone.utc) - timedelta(seconds=60.0 * (count - 1))
    payload = {"source_id": source.id, "sensor_id": sensor.id, "measurement_type": "temperature_c", "unit": "celsius", "count": count, "seed": seed, "start_at": start_at.isoformat()}
    if value_overrides:
        payload["value_overrides"] = value_overrides
    response = client.post("/api/v1/sensor-ingestion/synthetic-batches", json=payload, headers=auth_header(tokens, "analyst"))
    assert response.status_code == 201, response.text
    return response.json()


def test_timeseries_endpoint_returns_real_points(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    _ingest(client, tokens, auth_header, source, sensor, count=15, seed=50)
    response = client.get(
        f"/api/v1/sensor-analytics/sensors/{sensor.id}/timeseries", params={"measurement_type": "temperature_c"}, headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["returned_count"] == 15
    assert body["is_downsampled"] is False
    assert len(body["points"]) == 15


def test_timeseries_endpoint_downsamples_honestly(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    _ingest(client, tokens, auth_header, source, sensor, count=20, seed=51)
    response = client.get(
        f"/api/v1/sensor-analytics/sensors/{sensor.id}/timeseries",
        params={"measurement_type": "temperature_c", "max_points": 5}, headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_downsampled"] is True
    assert body["aggregation_note"] is not None
    assert len(body["points"]) <= 7


def test_statistics_endpoint(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    _ingest(client, tokens, auth_header, source, sensor, count=20, seed=52)
    response = client.get(
        f"/api/v1/sensor-analytics/sensors/{sensor.id}/statistics", params={"measurement_type": "temperature_c"}, headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid_count"] == 20
    assert body["insufficient_sample"] is False


def test_health_endpoint_never_connected(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    response = client.get(f"/api/v1/sensor-analytics/sensors/{sensor.id}/health", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200
    body = response.json()
    assert body["connectivity"]["status"] == "never_connected"
    assert body["anomaly_status"]["unresolved_count"] == 0


def test_health_recompute_requires_sensor_manage(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    _ingest(client, tokens, auth_header, source, sensor, count=5, seed=53)
    response = client.post(f"/api/v1/sensor-analytics/sensors/{sensor.id}/health/recompute", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 403

    response2 = client.post(f"/api/v1/sensor-analytics/sensors/{sensor.id}/health/recompute", headers=auth_header(tokens, "analyst"))
    assert response2.status_code == 200
    assert response2.json()["connectivity"]["status"] == "connected"


def test_run_anomaly_checks_endpoint(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    _ingest(client, tokens, auth_header, source, sensor, count=10, seed=54, value_overrides={"9": 99.0})
    response = client.post(
        "/api/v1/sensor-analytics/anomalies/run", json={"sensor_id": sensor.id, "measurement_type": "temperature_c"}, headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["created"]) > 0
    methods = {a["detection_method"] for a in body["created"]}
    assert "range_violation" in methods


def test_run_anomaly_checks_viewer_forbidden(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    response = client.post(
        "/api/v1/sensor-analytics/anomalies/run", json={"sensor_id": sensor.id, "measurement_type": "temperature_c"}, headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 403


def test_list_and_get_and_review_anomaly(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    _ingest(client, tokens, auth_header, source, sensor, count=10, seed=55, value_overrides={"9": 99.0})
    client.post("/api/v1/sensor-analytics/anomalies/run", json={"sensor_id": sensor.id, "measurement_type": "temperature_c"}, headers=auth_header(tokens, "analyst"))

    list_response = client.get("/api/v1/sensor-analytics/anomalies", headers=auth_header(tokens, "viewer"))
    assert list_response.status_code == 200
    anomalies = list_response.json()["items"]
    assert len(anomalies) > 0
    anomaly_id = anomalies[0]["id"]

    get_response = client.get(f"/api/v1/sensor-analytics/anomalies/{anomaly_id}", headers=auth_header(tokens, "viewer"))
    assert get_response.status_code == 200

    # Viewer can read but not review.
    forbidden = client.post(f"/api/v1/sensor-analytics/anomalies/{anomaly_id}/review", json={"review_status": "confirmed_unusual"}, headers=auth_header(tokens, "viewer"))
    assert forbidden.status_code == 403

    review_response = client.post(
        f"/api/v1/sensor-analytics/anomalies/{anomaly_id}/review", json={"review_status": "confirmed_unusual", "review_note": "verified"}, headers=auth_header(tokens, "analyst"),
    )
    assert review_response.status_code == 200, review_response.text
    assert review_response.json()["review_status"] == "confirmed_unusual"
    assert review_response.json()["category"] == "analyst_confirmed"


def test_review_anomaly_rejects_invalid_status(client, tokens, auth_header, db, org, source):
    sensor = _make_sensor(db, org, source)
    _ingest(client, tokens, auth_header, source, sensor, count=10, seed=56, value_overrides={"9": 99.0})
    client.post("/api/v1/sensor-analytics/anomalies/run", json={"sensor_id": sensor.id, "measurement_type": "temperature_c"}, headers=auth_header(tokens, "analyst"))
    anomaly_id = client.get("/api/v1/sensor-analytics/anomalies", headers=auth_header(tokens, "viewer")).json()["items"][0]["id"]
    response = client.post(f"/api/v1/sensor-analytics/anomalies/{anomaly_id}/review", json={"review_status": "not_a_real_status"}, headers=auth_header(tokens, "analyst"))
    assert response.status_code == 422


def test_timeseries_sensor_not_found(client, tokens, auth_header):
    response = client.get("/api/v1/sensor-analytics/sensors/does-not-exist/timeseries", params={"measurement_type": "temperature_c"}, headers=auth_header(tokens, "viewer"))
    assert response.status_code == 404
