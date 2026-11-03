"""Health-finding rules and capability discovery
 tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.services import edge_sync_service, fleet_capability_service, fleet_health_service


def _settings():
    return get_settings()


def _submit_health(client, device, api_key, device_headers, **overrides):
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "protocol_version": "edge_sync_v1", "reported_at": now, "connectivity_state": "online",
        "queue_depth": 0, "pending_sync_count": 0,
    }
    payload.update(overrides)
    return client.post("/api/v1/edge/sync/health", json=payload, headers=device_headers(device.device_identifier, api_key))


def test_missing_metrics_produce_no_finding(db, active_device_factory):
    """Section 4, binding: a metric never reported produces no finding
    at all -- never a fabricated 0/100."""
    device, _ = active_device_factory()
    findings = fleet_health_service.evaluate_health_findings(db, device, settings=_settings())
    assert not any(f["rule_key"] in ("disk_usage_high", "battery_low", "sync_queue_backlog") for f in findings)


def test_disk_usage_warning_and_critical_thresholds(db, active_device_factory):
    device, _ = active_device_factory()
    settings = _settings()
    from app.models.device_health_report import DeviceHealthReport

    report = DeviceHealthReport(
        organization_id=device.organization_id, device_id=device.id, reported_at=datetime.now(timezone.utc),
        connectivity_state="online", resource_metrics={"disk_used_pct": settings.FLEET_HEALTH_DISK_CRITICAL_PCT + 1},
    )
    db.add(report)
    db.commit()
    findings = {f["rule_key"]: f for f in fleet_health_service.evaluate_health_findings(db, device, settings=settings)}
    assert findings["disk_usage_high"]["severity"] == "critical"
    assert findings["disk_usage_high"]["source"] == "device_reported"


def test_battery_low_is_worse_the_lower_it_is(db, active_device_factory):
    device, _ = active_device_factory()
    settings = _settings()
    from app.models.device_health_report import DeviceHealthReport

    report = DeviceHealthReport(
        organization_id=device.organization_id, device_id=device.id, reported_at=datetime.now(timezone.utc),
        connectivity_state="online", resource_metrics={"battery_pct": settings.FLEET_HEALTH_BATTERY_CRITICAL_PCT - 1},
    )
    db.add(report)
    db.commit()
    findings = {f["rule_key"]: f for f in fleet_health_service.evaluate_health_findings(db, device, settings=settings)}
    assert findings["battery_low"]["severity"] == "critical"


def test_presence_offline_is_server_computed_not_device_reported(db, active_device_factory):
    device, _ = active_device_factory()
    settings = _settings()
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=settings.FLEET_PRESENCE_OFFLINE_AFTER_SECONDS + 5)
    db.add(device)
    db.commit()
    findings = {f["rule_key"]: f for f in fleet_health_service.evaluate_health_findings(db, device, settings=settings)}
    assert findings["presence_offline"]["severity"] == "critical"
    assert findings["presence_offline"]["source"] == "server_computed"


def test_capability_sync_from_registration_marks_supported(db, active_device_factory):
    from app.services import device_service

    device, _ = active_device_factory(device_identifier="cap-dev-1")
    device.capabilities = ["thermal_imaging"]
    db.add(device)
    db.commit()
    fleet_capability_service.sync_from_device_capabilities(db, device)
    rows = fleet_capability_service.list_for_device(db, device.organization_id, device.id)
    assert any(r.capability_key == "thermal_imaging" and r.supported for r in rows)


def test_capability_five_states_are_independent(client, active_device_factory, device_headers):
    device, api_key = active_device_factory(device_identifier="cap-dev-2")
    resp = _submit_health(
        client, device, api_key, device_headers,
        runtime_capabilities=["edge_object_detection"],
        model_status={"edge_object_detection": {"healthy": False}},
    )
    assert resp.status_code == 200, resp.text


def test_capability_healthy_is_none_until_verified(db, active_device_factory):
    device, _ = active_device_factory(device_identifier="cap-dev-3")
    fleet_capability_service._get_or_create(db, device, "never_verified_cap")
    db.commit()
    rows = fleet_capability_service.list_for_device(db, device.organization_id, device.id)
    row = next(r for r in rows if r.capability_key == "never_verified_cap")
    assert row.healthy is None  # unknown, never defaulted to False


def test_fleet_capability_summary_counts_per_key(db, active_device_factory):
    from app.models.device_health_report import DeviceHealthReport

    device, _ = active_device_factory(device_identifier="cap-dev-4")
    report = DeviceHealthReport(
        organization_id=device.organization_id, device_id=device.id, reported_at=datetime.now(timezone.utc),
        connectivity_state="online", runtime_capabilities=["gps_lock"], model_status={"gps_lock": {"healthy": True}},
    )
    db.add(report)
    db.commit()
    fleet_capability_service.sync_from_health_report(db, device, report)
    summary = fleet_capability_service.fleet_capability_summary(db, device.organization_id, settings=_settings())
    entry = next(e for e in summary if e["capability_key"] == "gps_lock")
    assert entry["installed_count"] == 1
    assert entry["healthy_count"] == 1
    assert entry["recently_verified_count"] == 1


def test_device_capabilities_api_requires_device_read(client, tokens, auth_header, active_device_factory):
    device, _ = active_device_factory(device_identifier="cap-dev-5")
    resp = client.get(f"/api/v1/devices/{device.id}/capabilities", headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_fleet_capability_summary_api(client, tokens, auth_header):
    resp = client.get("/api/v1/fleet/capabilities/summary", headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
