"""Asset and sensor registries, including the geolocation rule from
Section 7: a missing coordinate stays missing, and an out-of-range
coordinate is rejected -- never silently clamped or defaulted."""
from __future__ import annotations


def test_create_asset_with_coordinates(client, seeded_users, tokens, auth_header):
    response = client.post(
        "/api/v1/assets",
        json={"name": "North Gate", "entity_type": "facility", "latitude": 38.8977, "longitude": -77.0365},
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["latitude"] == 38.8977
    assert body["longitude"] == -77.0365


def test_create_asset_without_coordinates_stays_none(client, seeded_users, tokens, auth_header):
    response = client.post(
        "/api/v1/assets",
        json={"name": "Equipment Shed", "entity_type": "equipment"},
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 201
    body = response.json()
    # Must be None, never defaulted to 0.0/0.0.
    assert body["latitude"] is None
    assert body["longitude"] is None


def test_create_asset_rejects_out_of_range_latitude(client, seeded_users, tokens, auth_header):
    response = client.post(
        "/api/v1/assets",
        json={"name": "Bad Location", "entity_type": "facility", "latitude": 999.0, "longitude": 0.0},
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 422


def test_viewer_cannot_create_asset(client, seeded_users, tokens, auth_header):
    response = client.post(
        "/api/v1/assets",
        json={"name": "Nope", "entity_type": "facility"},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 403


def test_create_and_update_sensor(client, seeded_users, tokens, source, auth_header):
    create = client.post(
        "/api/v1/sensors",
        json={"name": "Gate Camera", "sensor_type": "camera", "source_id": source.id},
        headers=auth_header(tokens, "analyst"),
    )
    assert create.status_code == 201
    sensor_id = create.json()["id"]
    # A newly-registered sensor's operational status is "unknown" until
    # it actually reports in -- never defaulted to "active" just because
    # it was created.
    assert create.json()["status"] == "unknown"

    update = client.patch(
        f"/api/v1/sensors/{sensor_id}",
        json={"status": "active"},
        headers=auth_header(tokens, "analyst"),
    )
    assert update.status_code == 200
    assert update.json()["status"] == "active"


def test_get_unknown_asset_is_404(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/assets/not-a-real-id", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 404
