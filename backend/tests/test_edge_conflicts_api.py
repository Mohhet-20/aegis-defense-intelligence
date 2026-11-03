"""API tests for /edge/conflicts -- list,
inspect, resolve, and role-based authorization. Investigator is
deliberately granted EDGE_CONFLICT_MANAGE (case-work, see
app/core/security.py's Permission docstring) even though it lacks
DEVICE_MANAGE/EDGE_SYNC_MANAGE."""
from __future__ import annotations

from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _make_conflict(client, device_identifier, api_key):
    now = _now()
    env1 = {
        "message_id": "m1", "idempotency_key": "k1", "record_type": "annotation", "client_record_id": "ann1",
        "schema_version": "v1", "payload": {"text": "central"}, "source_created_at": now, "queued_at": now, "base_revision": 0,
    }
    headers = {"X-Device-Id": device_identifier, "X-Device-Api-Key": api_key}
    client.post("/api/v1/edge/sync/batch", json={"protocol_version": "edge_sync_v1", "device_id": device_identifier, "sent_at": now, "records": [env1]}, headers=headers)

    env2 = {
        "message_id": "m2", "idempotency_key": "k2", "record_type": "annotation", "client_record_id": "ann1",
        "schema_version": "v1", "payload": {"text": "stale"}, "source_created_at": now, "queued_at": now, "base_revision": 0,
    }
    resp = client.post("/api/v1/edge/sync/batch", json={"protocol_version": "edge_sync_v1", "device_id": device_identifier, "sent_at": now, "records": [env2]}, headers=headers)
    return resp.json()["results"][0]["conflict_id"]


def test_list_and_get_conflict(client, tokens, auth_header, active_device_factory):
    device, api_key = active_device_factory()
    conflict_id = _make_conflict(client, device.device_identifier, api_key)

    listed = client.get("/api/v1/edge/conflicts", headers=auth_header(tokens, "viewer"))
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    got = client.get(f"/api/v1/edge/conflicts/{conflict_id}", headers=auth_header(tokens, "viewer"))
    assert got.status_code == 200
    assert got.json()["resolution_status"] == "unresolved"
    assert got.json()["local_version"]["payload"] == {"text": "stale"}
    assert got.json()["central_version"]["payload"] == {"text": "central"}


def test_viewer_cannot_resolve_conflict(client, tokens, auth_header, active_device_factory):
    device, api_key = active_device_factory()
    conflict_id = _make_conflict(client, device.device_identifier, api_key)
    resp = client.post(f"/api/v1/edge/conflicts/{conflict_id}/resolve", json={"resolution_strategy": "keep_central"}, headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 403


def test_investigator_can_resolve_conflict(client, tokens, auth_header, active_device_factory):
    """Section 8.4/case-work split -- Investigator has
    EDGE_CONFLICT_MANAGE even without DEVICE_MANAGE/EDGE_SYNC_MANAGE."""
    device, api_key = active_device_factory()
    conflict_id = _make_conflict(client, device.device_identifier, api_key)
    resp = client.post(f"/api/v1/edge/conflicts/{conflict_id}/resolve", json={"resolution_strategy": "keep_local", "resolution_note": "device had the correct edit"}, headers=auth_header(tokens, "investigator"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["resolution_status"] == "resolved"
    assert resp.json()["resolved_by_user_id"]


def test_resolve_with_invalid_strategy_returns_400(client, tokens, auth_header, active_device_factory):
    device, api_key = active_device_factory()
    conflict_id = _make_conflict(client, device.device_identifier, api_key)
    resp = client.post(f"/api/v1/edge/conflicts/{conflict_id}/resolve", json={"resolution_strategy": "last_write_wins"}, headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 400


def test_resolve_twice_returns_400(client, tokens, auth_header, active_device_factory):
    device, api_key = active_device_factory()
    conflict_id = _make_conflict(client, device.device_identifier, api_key)
    first = client.post(f"/api/v1/edge/conflicts/{conflict_id}/resolve", json={"resolution_strategy": "keep_central"}, headers=auth_header(tokens, "analyst"))
    assert first.status_code == 200
    second = client.post(f"/api/v1/edge/conflicts/{conflict_id}/resolve", json={"resolution_strategy": "keep_local"}, headers=auth_header(tokens, "analyst"))
    assert second.status_code == 400


def test_conflict_not_found_returns_404(client, tokens, auth_header):
    resp = client.get("/api/v1/edge/conflicts/00000000-0000-0000-0000-000000000000", headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 404
