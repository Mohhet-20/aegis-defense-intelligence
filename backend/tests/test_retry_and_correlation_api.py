"""Job retry and the correlation API's list/get/review
surface end to end, through the real HTTP endpoints."""
from __future__ import annotations

import io


def _upload(client, header, source_id, content, filename="upload.json"):
    return client.post(
        "/api/v1/ingestion/jobs",
        data={"source_id": source_id},
        files={"file": (filename, io.BytesIO(content), "application/json")},
        headers=header,
    )


# --- retry --------------------------------------------------------------


def test_retrying_a_file_upload_job_is_refused_as_unsafe(client, seeded_users, tokens, source, auth_header):
    upload = _upload(client, auth_header(tokens, "analyst"), source.id, b'[{"event_type": "x", "title": "A", "observed_at": "2026-01-01T00:00:00Z"}]')
    job_id = upload.json()["id"]
    response = client.post(f"/api/v1/ingestion/jobs/{job_id}/retry", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 400
    assert "not safely retryable" in response.json()["detail"]


def test_retrying_a_connector_driven_job_runs_again_and_bumps_retry_count(client, seeded_users, tokens, auth_header):
    create = client.post(
        "/api/v1/sources",
        json={"name": "Retryable", "source_type": "synthetic_demo", "connection_mode": "polling", "config_metadata": {"count": 2, "seed": 5}},
        headers=auth_header(tokens, "analyst"),
    )
    source_id = create.json()["id"]
    first_run = client.post(f"/api/v1/sources/{source_id}/run", headers=auth_header(tokens, "analyst"))
    job_id = first_run.json()["id"]

    retry = client.post(f"/api/v1/ingestion/jobs/{job_id}/retry", headers=auth_header(tokens, "analyst"))
    assert retry.status_code == 201
    assert retry.json()["retry_count"] == 1
    # Same deterministic seed -> the "retry" is a fresh job that finds
    # everything a duplicate of the first run, never re-accepting it.
    assert retry.json()["duplicate_count"] == 2


def test_get_nonexistent_job_is_404(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/ingestion/jobs/does-not-exist", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 404


def test_retry_nonexistent_job_is_404(client, seeded_users, tokens, auth_header):
    response = client.post("/api/v1/ingestion/jobs/does-not-exist/retry", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 404


def test_raw_records_for_nonexistent_job_is_404(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/ingestion/jobs/does-not-exist/raw-records", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 404


# --- correlation API: list / get / recompute / review ---------------------


def _seed_two_correlatable_events(client, header, source_id):
    content = b"""[
        {"event_type": "a", "title": "E1", "observed_at": "2026-01-01T00:00:00Z", "external_id": "c-1", "latitude": 38.9, "longitude": -77.0},
        {"event_type": "a", "title": "E2", "observed_at": "2026-01-01T00:02:00Z", "external_id": "c-2", "latitude": 38.9001, "longitude": -77.0001}
    ]"""
    return _upload(client, header, source_id, content)


def test_full_correlation_workflow_through_the_api(client, seeded_users, tokens, source, auth_header):
    analyst = auth_header(tokens, "analyst")
    _seed_two_correlatable_events(client, analyst, source.id)

    recompute = client.post("/api/v1/correlation/recompute", json={}, headers=analyst)
    assert recompute.status_code == 200
    assert recompute.json()["correlations_created"] == 1

    listing = client.get("/api/v1/correlation", headers=analyst)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    correlation_id = listing.json()["items"][0]["id"]
    assert listing.json()["items"][0]["review_status"] == "candidate"

    detail = client.get(f"/api/v1/correlation/{correlation_id}", headers=analyst)
    assert detail.status_code == 200
    assert set(detail.json()["reasons"]) >= {"temporal_proximity", "spatial_proximity"}

    review = client.post(f"/api/v1/correlation/{correlation_id}/review", json={"review_status": "confirmed"}, headers=analyst)
    assert review.status_code == 200
    assert review.json()["review_status"] == "confirmed"
    assert review.json()["reviewed_at"] is not None


def test_get_nonexistent_correlation_is_404(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/correlation/does-not-exist", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 404


def test_review_nonexistent_correlation_is_404(client, seeded_users, tokens, auth_header):
    response = client.post("/api/v1/correlation/does-not-exist/review", json={"review_status": "confirmed"}, headers=auth_header(tokens, "analyst"))
    assert response.status_code == 404


def test_custom_recompute_window_is_honored(client, seeded_users, tokens, source, auth_header):
    analyst = auth_header(tokens, "analyst")
    _seed_two_correlatable_events(client, analyst, source.id)  # 2 minutes apart

    # A 60-second window is too narrow for these two events (2 minutes
    # apart) -- proves the request-supplied threshold actually reaches
    # the rule engine rather than always using the module default.
    narrow = client.post("/api/v1/correlation/recompute", json={"time_window_seconds": 60}, headers=analyst)
    assert narrow.json()["correlations_created"] == 0
