"""Additional API-level coverage for the Phase 9 route modules: 404
paths and the resolve/reopen alert endpoints not otherwise exercised."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.services import fleet_alert_service


def test_get_baseline_404(client, tokens, auth_header):
    resp = client.get("/api/v1/fleet/config-baselines/00000000-0000-0000-0000-000000000000", headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 404


def test_assign_unknown_baseline_404(client, tokens, auth_header, active_device_factory):
    device, _ = active_device_factory(device_identifier="cov-dev-1")
    resp = client.post(f"/api/v1/devices/{device.id}/config/baseline", json={"baseline_id": "00000000-0000-0000-0000-000000000000"}, headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 404


def test_assign_device_to_unknown_site_404(client, tokens, auth_header, active_device_factory):
    device, _ = active_device_factory(device_identifier="cov-dev-2")
    resp = client.post(f"/api/v1/devices/{device.id}/site", json={"site_id": "00000000-0000-0000-0000-000000000000"}, headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 404


def test_get_site_404(client, tokens, auth_header):
    resp = client.get("/api/v1/fleet/sites/00000000-0000-0000-0000-000000000000", headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 404


def test_site_summary_404(client, tokens, auth_header):
    resp = client.get("/api/v1/fleet/sites/00000000-0000-0000-0000-000000000000/summary", headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 404


def test_alert_404(client, tokens, auth_header):
    resp = client.get("/api/v1/fleet/alerts/00000000-0000-0000-0000-000000000000", headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 404


def test_resolve_and_reopen_alert_via_api(client, tokens, auth_header, active_device_factory, db):
    device, _ = active_device_factory(device_identifier="cov-dev-3")
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=get_settings().FLEET_PRESENCE_OFFLINE_AFTER_SECONDS + 10)
    db.add(device)
    db.commit()
    fleet_alert_service.evaluate_alerts_for_device(db, device)

    listed = client.get("/api/v1/fleet/alerts", params={"device_id": device.id}, headers=auth_header(tokens, "analyst"))
    alert_id = listed.json()["items"][0]["id"]

    resolved = client.post(f"/api/v1/fleet/alerts/{alert_id}/resolve", json={"note": "handled"}, headers=auth_header(tokens, "analyst"))
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    reopened = client.post(f"/api/v1/fleet/alerts/{alert_id}/reopen", json={"note": "recurred"}, headers=auth_header(tokens, "analyst"))
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "reopened"

    # illegal: reopening a non-resolved alert
    illegal = client.post(f"/api/v1/fleet/alerts/{alert_id}/reopen", json={}, headers=auth_header(tokens, "analyst"))
    assert illegal.status_code == 400


def test_resolve_404_and_reopen_404(client, tokens, auth_header):
    resp = client.post("/api/v1/fleet/alerts/00000000-0000-0000-0000-000000000000/resolve", json={}, headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 404
    resp = client.post("/api/v1/fleet/alerts/00000000-0000-0000-0000-000000000000/reopen", json={}, headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 404


def test_viewer_cannot_resolve_or_reopen(client, tokens, auth_header, active_device_factory, db):
    device, _ = active_device_factory(device_identifier="cov-dev-4")
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=get_settings().FLEET_PRESENCE_OFFLINE_AFTER_SECONDS + 10)
    db.add(device)
    db.commit()
    fleet_alert_service.evaluate_alerts_for_device(db, device)
    listed = client.get("/api/v1/fleet/alerts", params={"device_id": device.id}, headers=auth_header(tokens, "analyst"))
    alert_id = listed.json()["items"][0]["id"]
    resp = client.post(f"/api/v1/fleet/alerts/{alert_id}/resolve", json={}, headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 403
    resp = client.post(f"/api/v1/fleet/alerts/{alert_id}/reopen", json={}, headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 403
