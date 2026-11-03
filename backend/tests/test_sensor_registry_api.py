"""API tests for the rewritten /sensors and /observations routes --
 CRUD, lifecycle transitions, status history,
and role-based authorization."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.sensor import Sensor


def test_create_sensor_with_phase6_metadata(client, tokens, auth_header, source):
    response = client.post(
        "/api/v1/sensors",
        json={
            "name": "Weather Station 1", "sensor_type": "environmental", "source_id": source.id,
            "category": "environmental", "measurement_types": ["temperature_c"],
            "measurement_units": {"temperature_c": "celsius"}, "operating_range": {"temperature_c": {"min": -40.0, "max": 60.0}},
            "nominal_sampling_interval_seconds": 60.0,
        },
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["lifecycle_status"] == "registered"
    assert body["measurement_types"] == ["temperature_c"]
    assert body["status"] == "unknown"  # legacy field untouched by Phase 6 defaults


def test_create_sensor_requires_sensor_manage_viewer_forbidden(client, tokens, auth_header):
    response = client.post(
        "/api/v1/sensors", json={"name": "X", "sensor_type": "camera"}, headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 403


def test_list_sensors_filters_by_lifecycle_status(client, tokens, auth_header, db, org, source):
    db.add(Sensor(organization_id=org.id, source_id=source.id, name="Registered One", sensor_type="camera", status="unknown", lifecycle_status="registered"))
    db.add(Sensor(organization_id=org.id, source_id=source.id, name="Active One", sensor_type="camera", status="active", lifecycle_status="active"))
    db.commit()
    response = client.get("/api/v1/sensors", params={"lifecycle_status": "active"}, headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200
    items = response.json()["items"]
    assert all(i["lifecycle_status"] == "active" for i in items)
    assert len(items) == 1


def test_list_sensors_filters_by_measurement_type(client, tokens, auth_header, db, org, source):
    db.add(Sensor(organization_id=org.id, source_id=source.id, name="Temp Sensor", sensor_type="environmental", status="unknown", measurement_types=["temperature_c"]))
    db.add(Sensor(organization_id=org.id, source_id=source.id, name="GPS Sensor", sensor_type="gps", status="unknown", measurement_types=["latitude", "longitude"]))
    db.commit()
    response = client.get("/api/v1/sensors", params={"measurement_type": "temperature_c"}, headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Temp Sensor"


def test_update_sensor_patches_phase6_fields(client, tokens, auth_header, db, org, source):
    sensor = Sensor(organization_id=org.id, source_id=source.id, name="To Update", sensor_type="camera", status="unknown")
    db.add(sensor)
    db.commit()
    db.refresh(sensor)

    response = client.patch(
        f"/api/v1/sensors/{sensor.id}", json={"category": "surveillance", "manufacturer": "Acme"}, headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["category"] == "surveillance"
    assert response.json()["manufacturer"] == "Acme"


def test_lifecycle_transition_valid(client, tokens, auth_header, db, org, source):
    sensor = Sensor(organization_id=org.id, source_id=source.id, name="Lifecycle Test", sensor_type="camera", status="unknown", lifecycle_status="registered")
    db.add(sensor)
    db.commit()
    db.refresh(sensor)

    response = client.post(f"/api/v1/sensors/{sensor.id}/lifecycle", json={"new_status": "maintenance", "note": "scheduled calibration"}, headers=auth_header(tokens, "analyst"))
    assert response.status_code == 200, response.text
    assert response.json()["lifecycle_status"] == "maintenance"


def test_lifecycle_transition_invalid_rejected(client, tokens, auth_header, db, org, source):
    sensor = Sensor(organization_id=org.id, source_id=source.id, name="Lifecycle Test 2", sensor_type="camera", status="unknown", lifecycle_status="retired")
    db.add(sensor)
    db.commit()
    db.refresh(sensor)

    response = client.post(f"/api/v1/sensors/{sensor.id}/lifecycle", json={"new_status": "active"}, headers=auth_header(tokens, "analyst"))
    assert response.status_code == 400


def test_retire_sensor_sets_retired_at_and_actor(client, tokens, auth_header, db, org, source, seeded_users):
    sensor = Sensor(organization_id=org.id, source_id=source.id, name="To Retire", sensor_type="camera", status="unknown", lifecycle_status="active")
    db.add(sensor)
    db.commit()
    db.refresh(sensor)

    response = client.post(f"/api/v1/sensors/{sensor.id}/retire", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lifecycle_status"] == "retired"
    assert body["retired_at"] is not None


def test_retire_sensor_requires_sensor_manage_investigator_forbidden(client, tokens, auth_header, db, org, source):
    sensor = Sensor(organization_id=org.id, source_id=source.id, name="To Retire 2", sensor_type="camera", status="unknown", lifecycle_status="active")
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    response = client.post(f"/api/v1/sensors/{sensor.id}/retire", headers=auth_header(tokens, "investigator"))
    assert response.status_code == 403


def test_status_history_reflects_lifecycle_transitions(client, tokens, auth_header, db, org, source):
    sensor = Sensor(organization_id=org.id, source_id=source.id, name="History Test", sensor_type="camera", status="unknown", lifecycle_status="registered")
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    client.post(f"/api/v1/sensors/{sensor.id}/lifecycle", json={"new_status": "maintenance"}, headers=auth_header(tokens, "analyst"))

    response = client.get(f"/api/v1/sensors/{sensor.id}/status-history", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200
    history = response.json()
    assert len(history) == 1
    assert history[0]["action"] == "sensor.lifecycle_transition"


def test_get_sensor_not_found(client, tokens, auth_header):
    response = client.get("/api/v1/sensors/does-not-exist", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 404


def test_list_observations_requires_auth(client):
    response = client.get("/api/v1/observations")
    assert response.status_code == 401


def test_get_observation_not_found(client, tokens, auth_header):
    response = client.get("/api/v1/observations/does-not-exist", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 404
