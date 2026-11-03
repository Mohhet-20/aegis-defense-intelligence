"""Security / abuse-resistance tests for Phase 2's new surface
: SSRF end-to-end through the real API (not just the
url_safety unit), CSV export formula-injection guarding, export size
bounding, and permission gates on the newly-added sensitive endpoints.
"""
from __future__ import annotations

import io

from app.services import export_service


def _upload(client, header, source_id, content, filename="upload.json"):
    return client.post(
        "/api/v1/ingestion/jobs",
        data={"source_id": source_id},
        files={"file": (filename, io.BytesIO(content), "application/json")},
        headers=header,
    )


# --- SSRF end-to-end --------------------------------------------------


def test_http_source_pointed_at_cloud_metadata_fails_safely_not_a_500(client, seeded_users, tokens, auth_header):
    create = client.post(
        "/api/v1/sources",
        json={
            "name": "Metadata Probe",
            "source_type": "http_api",
            "connection_mode": "polling",
            "config_metadata": {"url": "http://169.254.169.254/latest/meta-data/", "allow_local_dev": True},
        },
        headers=auth_header(tokens, "analyst"),
    )
    source_id = create.json()["id"]

    validate = client.post(f"/api/v1/sources/{source_id}/validate-config", headers=auth_header(tokens, "analyst"))
    assert validate.json()["valid"] is False

    run = client.post(f"/api/v1/sources/{source_id}/run", headers=auth_header(tokens, "analyst"))
    assert run.status_code == 201  # a job IS created -- but marked failed, never a 500 and never any records
    assert run.json()["status"] == "failed"
    assert run.json()["accepted_count"] == 0


def test_http_source_with_a_non_https_url_is_rejected_by_default(client, seeded_users, tokens, auth_header):
    create = client.post(
        "/api/v1/sources",
        json={"name": "Plain HTTP", "source_type": "http_api", "config_metadata": {"url": "http://example.com/feed"}},
        headers=auth_header(tokens, "analyst"),
    )
    source_id = create.json()["id"]
    validate = client.post(f"/api/v1/sources/{source_id}/validate-config", headers=auth_header(tokens, "analyst"))
    assert validate.json()["valid"] is False


# --- CSV formula injection ---------------------------------------------


def test_csv_export_neutralizes_formula_injection():
    class FakeEvent:
        id = "1"
        source_id = "s1"
        external_id = "e1"
        event_type = "x"
        title = "=cmd|' /C calc'!A1"
        description = "+2+3"
        observed_at = None
        ingested_at = None
        latitude = None
        longitude = None
        source_severity = None
        priority = None
        confidence = None
        classification = "unclassified"
        processing_status = "normalized"
        data_origin = "user_upload"

    csv_text = export_service.export_events_csv([FakeEvent()])
    # Every formula-triggering cell must be neutralized with a leading
    # quote -- a raw unescaped "=..." must never reach the CSV body.
    assert "\n=cmd" not in csv_text
    assert "'=cmd" in csv_text
    assert "'+2+3" in csv_text


def test_event_export_endpoint_also_guards_against_formula_injection(client, seeded_users, tokens, source, auth_header):
    content = b'[{"event_type": "x", "title": "=1+1", "observed_at": "2026-01-01T00:00:00Z"}]'
    _upload(client, auth_header(tokens, "analyst"), source.id, content)
    response = client.get("/api/v1/events/export?format=csv", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 200
    assert "\n=1+1" not in response.text
    assert "'=1+1" in response.text


# --- export size bound + permission gate -----------------------------


def test_export_is_refused_when_it_would_exceed_the_row_limit(client, seeded_users, tokens, source, auth_header, monkeypatch):
    monkeypatch.setattr(export_service, "MAX_EXPORT_ROWS", 1)
    content = b"""[
        {"event_type": "x", "title": "A", "observed_at": "2026-01-01T00:00:00Z", "external_id": "e1"},
        {"event_type": "x", "title": "B", "observed_at": "2026-01-01T00:00:00Z", "external_id": "e2"}
    ]"""
    _upload(client, auth_header(tokens, "analyst"), source.id, content)
    response = client.get("/api/v1/events/export", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 400
    assert "narrow the filters" in response.json()["detail"]


def test_export_requires_data_export_permission_not_just_event_read(client, seeded_users, tokens, auth_header):
    # viewer has EVENT_READ but not DATA_EXPORT
    response = client.get("/api/v1/events/export", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 403


def test_raw_record_access_requires_its_own_permission(client, seeded_users, tokens, source, auth_header):
    content = b'[{"event_type": "x", "title": "A", "observed_at": "2026-01-01T00:00:00Z", "external_id": "perm-1"}]'
    _upload(client, auth_header(tokens, "analyst"), source.id, content)
    events = client.get("/api/v1/events", headers=auth_header(tokens, "viewer")).json()["items"]
    event_id = next(e["id"] for e in events if e["external_id"] == "perm-1")

    viewer_resp = client.get(f"/api/v1/events/{event_id}/raw-record", headers=auth_header(tokens, "viewer"))
    assert viewer_resp.status_code == 403

    analyst_resp = client.get(f"/api/v1/events/{event_id}/raw-record", headers=auth_header(tokens, "analyst"))
    assert analyst_resp.status_code == 200
    assert analyst_resp.json()["payload"]["title"] == "A"


def test_job_raw_records_listing_requires_raw_record_permission(client, seeded_users, tokens, source, auth_header):
    upload = _upload(client, auth_header(tokens, "analyst"), source.id, b'[{"event_type": "x", "title": "A", "observed_at": "2026-01-01T00:00:00Z"}]')
    job_id = upload.json()["id"]

    viewer_resp = client.get(f"/api/v1/ingestion/jobs/{job_id}/raw-records", headers=auth_header(tokens, "viewer"))
    assert viewer_resp.status_code == 403

    analyst_resp = client.get(f"/api/v1/ingestion/jobs/{job_id}/raw-records", headers=auth_header(tokens, "analyst"))
    assert analyst_resp.status_code == 200
    assert analyst_resp.json()["total"] == 1


# --- oversized / malformed upload handling (still enforced post-rewire) ---


def test_oversized_upload_is_still_rejected_cleanly(client, seeded_users, tokens, source, auth_header, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 10)
    response = _upload(client, auth_header(tokens, "analyst"), source.id, b'[{"event_type": "far too big for the limit"}]')
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert "byte upload limit" in response.json()["error_summary"][0]["error"]


def test_deeply_malformed_json_upload_fails_the_job_not_the_server(client, seeded_users, tokens, source, auth_header):
    response = _upload(client, auth_header(tokens, "analyst"), source.id, b"this is not json {{{")
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
