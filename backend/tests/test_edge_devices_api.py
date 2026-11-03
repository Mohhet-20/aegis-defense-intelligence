"""API tests for /devices -- registration,
listing/filtering, lifecycle transitions, key rotation, health-report
history, and role-based authorization (DEVICE_READ/DEVICE_MANAGE)."""
from __future__ import annotations


def test_register_device_requires_device_manage(client, tokens, auth_header):
    resp = client.post(
        "/api/v1/devices", json={"device_identifier": "api-dev-1", "device_name": "API Device", "device_type": "field_sensor_node"},
        headers=auth_header(tokens, "analyst"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["device"]["administrative_status"] == "pending"
    assert body["api_key"].startswith("edge_")


def test_viewer_cannot_register_device(client, tokens, auth_header):
    resp = client.post(
        "/api/v1/devices", json={"device_identifier": "api-dev-2", "device_name": "X", "device_type": "y"},
        headers=auth_header(tokens, "viewer"),
    )
    assert resp.status_code == 403


def test_investigator_can_read_but_not_manage_devices(client, tokens, auth_header):
    resp = client.get("/api/v1/devices", headers=auth_header(tokens, "investigator"))
    assert resp.status_code == 200
    resp = client.post(
        "/api/v1/devices", json={"device_identifier": "api-dev-3", "device_name": "X", "device_type": "y"},
        headers=auth_header(tokens, "investigator"),
    )
    assert resp.status_code == 403


def test_duplicate_device_identifier_returns_409(client, tokens, auth_header):
    payload = {"device_identifier": "api-dev-dup", "device_name": "D", "device_type": "field_sensor_node"}
    first = client.post("/api/v1/devices", json=payload, headers=auth_header(tokens, "analyst"))
    assert first.status_code == 201
    second = client.post("/api/v1/devices", json=payload, headers=auth_header(tokens, "analyst"))
    assert second.status_code == 409


def test_full_lifecycle_through_the_api(client, tokens, auth_header):
    reg = client.post(
        "/api/v1/devices", json={"device_identifier": "api-lifecycle-1", "device_name": "D", "device_type": "field_sensor_node"},
        headers=auth_header(tokens, "analyst"),
    ).json()
    device_id = reg["device"]["id"]

    activated = client.post(f"/api/v1/devices/{device_id}/activate", json={"reason": "go live"}, headers=auth_header(tokens, "analyst"))
    assert activated.status_code == 200
    assert activated.json()["administrative_status"] == "active"

    suspended = client.post(f"/api/v1/devices/{device_id}/suspend", json={"reason": "investigating"}, headers=auth_header(tokens, "analyst"))
    assert suspended.status_code == 200
    assert suspended.json()["administrative_status"] == "suspended"

    reactivated = client.post(f"/api/v1/devices/{device_id}/activate", json={}, headers=auth_header(tokens, "analyst"))
    assert reactivated.status_code == 200

    revoked = client.post(f"/api/v1/devices/{device_id}/revoke", json={"reason": "decommissioned"}, headers=auth_header(tokens, "analyst"))
    assert revoked.status_code == 200
    assert revoked.json()["administrative_status"] == "revoked"

    # revoked -> active is illegal and returns 400, not 500
    illegal = client.post(f"/api/v1/devices/{device_id}/activate", json={}, headers=auth_header(tokens, "analyst"))
    assert illegal.status_code == 400

    history = client.get(f"/api/v1/devices/{device_id}/status-history", headers=auth_header(tokens, "analyst"))
    assert history.status_code == 200
    actions = [h["action"] for h in history.json()]
    assert "device.register" in actions
    assert "device.lifecycle_transition" in actions


def test_rotate_key_issues_a_new_key_and_old_one_stops_working(client, tokens, auth_header, device_headers):
    reg = client.post(
        "/api/v1/devices", json={"device_identifier": "api-rotate-1", "device_name": "D", "device_type": "field_sensor_node"},
        headers=auth_header(tokens, "analyst"),
    ).json()
    device_id = reg["device"]["id"]
    old_key = reg["api_key"]
    client.post(f"/api/v1/devices/{device_id}/activate", json={}, headers=auth_header(tokens, "analyst"))

    rotated = client.post(f"/api/v1/devices/{device_id}/rotate-key", headers=auth_header(tokens, "analyst"))
    assert rotated.status_code == 200
    new_key = rotated.json()["api_key"]
    assert new_key != old_key

    import datetime

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    batch = {
        "protocol_version": "edge_sync_v1", "device_id": "api-rotate-1", "sent_at": now,
        "records": [{"message_id": "m1", "idempotency_key": "k1", "record_type": "observation_capture", "client_record_id": "cr1", "schema_version": "v1", "payload": {"x": 1}, "source_created_at": now, "queued_at": now}],
    }
    with_old = client.post("/api/v1/edge/sync/batch", json=batch, headers=device_headers("api-rotate-1", old_key))
    assert with_old.status_code == 401
    with_new = client.post("/api/v1/edge/sync/batch", json=batch, headers=device_headers("api-rotate-1", new_key))
    assert with_new.status_code == 200


def test_list_devices_filters_by_administrative_status(client, tokens, auth_header):
    pending_reg = client.post(
        "/api/v1/devices", json={"device_identifier": "api-filter-pending", "device_name": "D", "device_type": "field_sensor_node"},
        headers=auth_header(tokens, "analyst"),
    ).json()
    active_reg = client.post(
        "/api/v1/devices", json={"device_identifier": "api-filter-active", "device_name": "D", "device_type": "field_sensor_node"},
        headers=auth_header(tokens, "analyst"),
    ).json()
    client.post(f"/api/v1/devices/{active_reg['device']['id']}/activate", json={}, headers=auth_header(tokens, "analyst"))

    resp = client.get("/api/v1/devices", params={"administrative_status": "active"}, headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(i["administrative_status"] == "active" for i in items)
    assert any(i["id"] == active_reg["device"]["id"] for i in items)
    assert all(i["id"] != pending_reg["device"]["id"] for i in items)


def test_device_not_found_returns_404(client, tokens, auth_header):
    resp = client.get("/api/v1/devices/00000000-0000-0000-0000-000000000000", headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 404


def test_illegal_lifecycle_transition_via_api_returns_400(client, tokens, auth_header):
    reg = client.post(
        "/api/v1/devices", json={"device_identifier": "api-illegal-1", "device_name": "D", "device_type": "field_sensor_node"},
        headers=auth_header(tokens, "analyst"),
    ).json()
    device_id = reg["device"]["id"]
    # still "pending" -- suspend is only legal from "active"
    resp = client.post(f"/api/v1/devices/{device_id}/suspend", json={}, headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 400


def test_rotate_key_on_revoked_device_returns_400(client, tokens, auth_header):
    reg = client.post(
        "/api/v1/devices", json={"device_identifier": "api-rotaterevoke-1", "device_name": "D", "device_type": "field_sensor_node"},
        headers=auth_header(tokens, "analyst"),
    ).json()
    device_id = reg["device"]["id"]
    client.post(f"/api/v1/devices/{device_id}/activate", json={}, headers=auth_header(tokens, "analyst"))
    client.post(f"/api/v1/devices/{device_id}/revoke", json={}, headers=auth_header(tokens, "analyst"))

    resp = client.post(f"/api/v1/devices/{device_id}/rotate-key", headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 400


def test_health_report_history_endpoint(client, tokens, auth_header, device_headers):
    reg = client.post(
        "/api/v1/devices", json={"device_identifier": "api-health-1", "device_name": "D", "device_type": "field_sensor_node"},
        headers=auth_header(tokens, "analyst"),
    ).json()
    device_id = reg["device"]["id"]
    client.post(f"/api/v1/devices/{device_id}/activate", json={}, headers=auth_header(tokens, "analyst"))

    import datetime

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    health_payload = {"protocol_version": "edge_sync_v1", "reported_at": now, "connectivity_state": "online", "queue_depth": 2, "pending_sync_count": 2}
    submit = client.post("/api/v1/edge/sync/health", json=health_payload, headers=device_headers("api-health-1", reg["api_key"]))
    assert submit.status_code == 200

    history = client.get(f"/api/v1/devices/{device_id}/health-reports", headers=auth_header(tokens, "viewer"))
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["queue_depth"] == 2
