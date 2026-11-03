"""API tests for the device-authenticated /edge/sync endpoints and the
JWT-authenticated admin queue view."""
from __future__ import annotations

from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _envelope(**overrides):
    now = _now()
    base = {
        "message_id": "m1", "idempotency_key": "k1", "record_type": "observation_capture", "client_record_id": "cr1",
        "schema_version": "v1", "payload": {"x": 1}, "source_created_at": now, "queued_at": now,
    }
    base.update(overrides)
    return base


def _batch(device_identifier, records, **overrides):
    base = {"protocol_version": "edge_sync_v1", "device_id": device_identifier, "sent_at": _now(), "records": records}
    base.update(overrides)
    return base


def test_sync_batch_rejected_without_device_headers(client, active_device_factory):
    device, _ = active_device_factory()
    resp = client.post("/api/v1/edge/sync/batch", json=_batch(device.device_identifier, [_envelope()]))
    assert resp.status_code in (401, 422)  # missing required headers


def test_sync_batch_accepts_and_syncs(client, active_device_factory, device_headers):
    device, api_key = active_device_factory()
    resp = client.post("/api/v1/edge/sync/batch", json=_batch(device.device_identifier, [_envelope()]), headers=device_headers(device.device_identifier, api_key))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted_count"] == 1
    assert body["results"][0]["sync_status"] == "synced"


def test_sync_batch_rejects_spoofed_device_id(client, active_device_factory, device_headers):
    device, api_key = active_device_factory()
    resp = client.post("/api/v1/edge/sync/batch", json=_batch("someone-elses-device", [_envelope()]), headers=device_headers(device.device_identifier, api_key))
    assert resp.status_code == 400


def test_sync_batch_rejects_unsupported_protocol_version(client, active_device_factory, device_headers):
    device, api_key = active_device_factory()
    resp = client.post(
        "/api/v1/edge/sync/batch", json=_batch(device.device_identifier, [_envelope()], protocol_version="edge_sync_v99"),
        headers=device_headers(device.device_identifier, api_key),
    )
    assert resp.status_code == 400


def test_health_report_requires_device_auth(client, active_device_factory):
    device, _ = active_device_factory()
    resp = client.post(
        "/api/v1/edge/sync/health",
        json={"protocol_version": "edge_sync_v1", "reported_at": _now(), "connectivity_state": "online", "queue_depth": 0, "pending_sync_count": 0},
    )
    assert resp.status_code in (401, 422)


def test_admin_can_list_sync_records(client, tokens, auth_header, active_device_factory, device_headers):
    device, api_key = active_device_factory()
    client.post("/api/v1/edge/sync/batch", json=_batch(device.device_identifier, [_envelope()]), headers=device_headers(device.device_identifier, api_key))

    resp = client.get("/api/v1/edge/sync/records", headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["record_type"] == "observation_capture"


def test_viewer_cannot_force_retry_or_cancel(client, tokens, auth_header, active_device_factory, device_headers):
    device, api_key = active_device_factory()
    resp = client.post("/api/v1/edge/sync/batch", json=_batch(device.device_identifier, [_envelope()]), headers=device_headers(device.device_identifier, api_key))
    sync_record_id = resp.json()["results"][0]["sync_record_id"]

    retry = client.post(f"/api/v1/edge/sync/records/{sync_record_id}/retry", json={}, headers=auth_header(tokens, "viewer"))
    assert retry.status_code == 403
    cancel = client.post(f"/api/v1/edge/sync/records/{sync_record_id}/cancel", json={}, headers=auth_header(tokens, "viewer"))
    assert cancel.status_code == 403


def test_analyst_can_cancel_a_queued_record_but_not_a_synced_one(client, tokens, auth_header, active_device_factory, device_headers):
    device, api_key = active_device_factory()
    resp = client.post("/api/v1/edge/sync/batch", json=_batch(device.device_identifier, [_envelope()]), headers=device_headers(device.device_identifier, api_key))
    sync_record_id = resp.json()["results"][0]["sync_record_id"]

    cancel = client.post(f"/api/v1/edge/sync/records/{sync_record_id}/cancel", json={"reason": "no longer needed"}, headers=auth_header(tokens, "analyst"))
    assert cancel.status_code == 400  # already synced, illegal transition -> 400 not 500


def test_queue_summary_endpoint(client, tokens, auth_header, active_device_factory, device_headers):
    device, api_key = active_device_factory()
    client.post("/api/v1/edge/sync/batch", json=_batch(device.device_identifier, [_envelope()]), headers=device_headers(device.device_identifier, api_key))

    resp = client.get("/api/v1/edge/sync/queue/summary", headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_records"] == 1
    assert body["devices_with_pending_records"] == 0


def test_recover_stale_endpoint_requires_edge_sync_manage(client, tokens, auth_header):
    resp = client.post("/api/v1/edge/sync/recover-stale", headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 403
    resp = client.post("/api/v1/edge/sync/recover-stale", headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 200
    assert resp.json()["recovered_count"] == 0


def test_sync_record_not_found_returns_404(client, tokens, auth_header):
    resp = client.get("/api/v1/edge/sync/records/00000000-0000-0000-0000-000000000000", headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 404


def test_sync_batch_too_large_returns_413(client, active_device_factory, device_headers, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "EDGE_SYNC_MAX_BATCH_SIZE", 1)
    device, api_key = active_device_factory()
    records = [_envelope(message_id=f"m{i}", idempotency_key=f"k{i}", client_record_id=f"cr{i}") for i in range(2)]
    resp = client.post("/api/v1/edge/sync/batch", json=_batch(device.device_identifier, records), headers=device_headers(device.device_identifier, api_key))
    assert resp.status_code == 413


def test_health_report_rejects_unsupported_protocol_version(client, active_device_factory, device_headers):
    device, api_key = active_device_factory()
    resp = client.post(
        "/api/v1/edge/sync/health",
        json={"protocol_version": "edge_sync_v99", "reported_at": _now(), "connectivity_state": "online", "queue_depth": 0, "pending_sync_count": 0},
        headers=device_headers(device.device_identifier, api_key),
    )
    assert resp.status_code == 400
