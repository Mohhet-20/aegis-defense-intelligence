

def test_list_survives_a_stored_out_of_range_coordinate(client, db, org, source, seeded_users, tokens, auth_header):
    """Regression (KNOWN_RISKS 33): one legacy/direct-write row with latitude 123 made
    GET /events fail response validation with a 500 for the whole page."""
    from datetime import datetime, timezone

    from app.models.event import Event

    db.add(Event(organization_id=org.id, source_id=source.id, event_type="perimeter_motion", title="bad coords",
                 observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                 data_origin="user_upload", latitude=123.0, longitude=-77.0))
    db.commit()
    r = client.get("/api/v1/events", headers=auth_header(tokens, "analyst"))
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["latitude"] == 123.0     # shown as stored, not hidden or invented
