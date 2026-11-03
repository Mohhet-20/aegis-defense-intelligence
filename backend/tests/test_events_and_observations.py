"""Event retrieval/filtering, and observation listing."""
from __future__ import annotations

import io


def _upload_events(client, token_header, source_id, records_json: bytes):
    return client.post(
        "/api/v1/ingestion/jobs",
        data={"source_id": source_id},
        files={"file": ("upload.json", io.BytesIO(records_json), "application/json")},
        headers=token_header,
    )


def test_list_events_after_ingestion(client, seeded_users, tokens, source, auth_header):
    content = b"""[
        {"event_type": "perimeter_motion", "title": "Motion A", "observed_at": "2026-01-01T00:00:00Z"},
        {"event_type": "sensor_offline", "title": "Offline A", "observed_at": "2026-01-02T00:00:00Z"}
    ]"""
    _upload_events(client, auth_header(tokens, "analyst"), source.id, content)

    response = client.get("/api/v1/events", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2


def test_filter_events_by_event_type(client, seeded_users, tokens, source, auth_header):
    content = b"""[
        {"event_type": "perimeter_motion", "title": "Motion A", "observed_at": "2026-01-01T00:00:00Z"},
        {"event_type": "sensor_offline", "title": "Offline A", "observed_at": "2026-01-02T00:00:00Z"}
    ]"""
    _upload_events(client, auth_header(tokens, "analyst"), source.id, content)

    response = client.get(
        "/api/v1/events", params={"event_type": "sensor_offline"}, headers=auth_header(tokens, "viewer")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["event_type"] == "sensor_offline"


def test_get_single_event_and_404_for_missing(client, seeded_users, tokens, source, auth_header, db):
    from app.models.event import Event

    content = b'[{"event_type": "perimeter_motion", "title": "Motion A", "observed_at": "2026-01-01T00:00:00Z"}]'
    _upload_events(client, auth_header(tokens, "analyst"), source.id, content)

    event = db.query(Event).first()
    response = client.get(f"/api/v1/events/{event.id}", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200
    assert response.json()["title"] == "Motion A"

    missing = client.get("/api/v1/events/not-a-real-id", headers=auth_header(tokens, "viewer"))
    assert missing.status_code == 404


def test_list_observations_filtered_by_sensor(client, db, org, seeded_users, tokens, source, auth_header):
    from datetime import datetime, timezone

    from app.models.observation import Observation
    from app.models.sensor import Sensor

    sensor_a = Sensor(organization_id=org.id, source_id=source.id, name="Sensor A", sensor_type="camera", status="active")
    sensor_b = Sensor(organization_id=org.id, source_id=source.id, name="Sensor B", sensor_type="gps", status="active")
    db.add_all([sensor_a, sensor_b])
    db.flush()

    db.add_all(
        [
            Observation(
                organization_id=org.id, sensor_id=sensor_a.id, source_id=source.id,
                observed_at=datetime.now(timezone.utc), observation_type="detection_summary",
                payload={}, data_origin="synthetic_demo",
            ),
            Observation(
                organization_id=org.id, sensor_id=sensor_b.id, source_id=source.id,
                observed_at=datetime.now(timezone.utc), observation_type="detection_summary",
                payload={}, data_origin="synthetic_demo",
            ),
        ]
    )
    db.commit()

    response = client.get(
        "/api/v1/observations", params={"sensor_id": sensor_a.id}, headers=auth_header(tokens, "viewer")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["sensor_id"] == sensor_a.id
