"""Dashboard summary: every figure must be a real aggregate against the
real database, never a hardcoded placeholder (Rule 3)."""
from __future__ import annotations

import io


def test_dashboard_summary_reflects_real_counts(client, seeded_users, tokens, source, auth_header):
    response = client.get("/api/v1/dashboard/summary", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200
    body = response.json()
    assert body["total_events"] == 0
    assert body["active_sources"] == 1
    assert body["synthetic_data_present"] is False

    content = b'[{"event_type": "test_event", "title": "Counted event", "observed_at": "2026-01-01T00:00:00Z"}]'
    client.post(
        "/api/v1/ingestion/jobs",
        data={"source_id": source.id},
        files={"file": ("upload.json", io.BytesIO(content), "application/json")},
        headers=auth_header(tokens, "analyst"),
    )

    response = client.get("/api/v1/dashboard/summary", headers=auth_header(tokens, "viewer"))
    body = response.json()
    assert body["total_events"] == 1
    assert body["ingestion_jobs_last_24h"] == 1
    # This event came from a real upload, not the seed script -- the
    # synthetic indicator must stay false.
    assert body["synthetic_data_present"] is False


def test_dashboard_open_to_every_role(client, seeded_users, tokens, auth_header):
    for role in ("admin", "analyst", "investigator", "viewer"):
        response = client.get("/api/v1/dashboard/summary", headers=auth_header(tokens, role))
        assert response.status_code == 200
