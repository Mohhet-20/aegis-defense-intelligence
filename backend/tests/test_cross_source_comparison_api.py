"""API tests for /cross-source-comparison."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.observation import Observation
from app.models.sensor import Sensor


def _make_sensor(db, org, source, **overrides) -> Sensor:
    defaults = dict(organization_id=org.id, source_id=source.id, name="XSC API Sensor", sensor_type="environmental", status="active")
    defaults.update(overrides)
    sensor = Sensor(**defaults)
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor


def _make_observation(db, org, sensor, source, *, value, unit) -> Observation:
    obs = Observation(
        organization_id=org.id, sensor_id=sensor.id, source_id=source.id, observed_at=datetime.now(timezone.utc),
        observation_type="temperature_c", payload={}, measurement_value=value, unit=unit,
        validation_status="valid", data_origin="synthetic_demo",
    )
    db.add(obs)
    db.commit()
    db.refresh(obs)
    return obs


def test_compare_endpoint_readable_by_viewer(client, tokens, auth_header, db, org, source):
    sensor_a = _make_sensor(db, org, source, name="A")
    sensor_b = _make_sensor(db, org, source, name="B")
    obs_a = _make_observation(db, org, sensor_a, source, value=22.0, unit="celsius")
    obs_b = _make_observation(db, org, sensor_b, source, value=22.3, unit="celsius")

    response = client.post(
        "/api/v1/cross-source-comparison/compare",
        json={"observation_a_id": obs_a.id, "observation_b_id": obs_b.id, "tolerance": 1.0},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conflicting"] is False
    assert body["same_measurement_type"] is True


def test_compare_endpoint_404_for_unknown_observation(client, tokens, auth_header, db, org, source):
    sensor_a = _make_sensor(db, org, source, name="A")
    obs_a = _make_observation(db, org, sensor_a, source, value=22.0, unit="celsius")
    response = client.post(
        "/api/v1/cross-source-comparison/compare",
        json={"observation_a_id": obs_a.id, "observation_b_id": "does-not-exist"},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 404


def test_create_link_requires_relationship_manage(client, tokens, auth_header, db, org, source):
    sensor_a = _make_sensor(db, org, source, name="A")
    sensor_b = _make_sensor(db, org, source, name="B")
    obs_a = _make_observation(db, org, sensor_a, source, value=22.0, unit="celsius")
    obs_b = _make_observation(db, org, sensor_b, source, value=22.3, unit="celsius")

    forbidden = client.post(
        "/api/v1/cross-source-comparison/links",
        json={"observation_a_id": obs_a.id, "observation_b_id": obs_b.id, "tolerance": 1.0},
        headers=auth_header(tokens, "viewer"),
    )
    assert forbidden.status_code == 403

    response = client.post(
        "/api/v1/cross-source-comparison/links",
        json={"observation_a_id": obs_a.id, "observation_b_id": obs_b.id, "tolerance": 1.0},
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 201, response.text
    assert response.json()["relationship_type"] == "cross_source_comparison"


def test_create_link_idempotent_via_api(client, tokens, auth_header, db, org, source):
    sensor_a = _make_sensor(db, org, source, name="A")
    sensor_b = _make_sensor(db, org, source, name="B")
    obs_a = _make_observation(db, org, sensor_a, source, value=22.0, unit="celsius")
    obs_b = _make_observation(db, org, sensor_b, source, value=22.3, unit="celsius")

    first = client.post(
        "/api/v1/cross-source-comparison/links",
        json={"observation_a_id": obs_a.id, "observation_b_id": obs_b.id, "tolerance": 1.0},
        headers=auth_header(tokens, "analyst"),
    )
    second = client.post(
        "/api/v1/cross-source-comparison/links",
        json={"observation_a_id": obs_a.id, "observation_b_id": obs_b.id, "tolerance": 1.0},
        headers=auth_header(tokens, "analyst"),
    )
    assert first.json()["id"] == second.json()["id"]
