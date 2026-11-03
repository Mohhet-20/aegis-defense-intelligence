"""Fleet sites/groups and fleet analytics
 tests, including tenant isolation."""
from __future__ import annotations

from datetime import datetime, timezone

from app.services import device_service, fleet_analytics_service, fleet_site_service


def test_create_site_without_coordinates_never_defaults_to_zero_zero(db, org, seeded_users):
    site = fleet_site_service.create_site(db, organization_id=org.id, actor_user_id=seeded_users["admin"].id, name="Warehouse A")
    assert site.latitude is None
    assert site.longitude is None


def test_assign_device_to_site_and_summary(db, org, seeded_users, active_device_factory):
    site = fleet_site_service.create_site(db, organization_id=org.id, actor_user_id=seeded_users["admin"].id, name="Forward Base Alpha", latitude=1.0, longitude=2.0)
    device, _ = active_device_factory(device_identifier="site-dev-1")
    device = fleet_site_service.assign_device_to_site(db, device, site, actor_user_id=seeded_users["admin"].id)
    assert device.site_id == site.id

    summary = fleet_site_service.site_summary(db, org.id, site)
    assert summary["device_count"] == 1
    assert sum(summary["administrative_status_counts"].values()) == 1


def test_unassign_device_from_site(db, org, seeded_users, active_device_factory):
    site = fleet_site_service.create_site(db, organization_id=org.id, actor_user_id=seeded_users["admin"].id, name="Site B")
    device, _ = active_device_factory(device_identifier="site-dev-2")
    device = fleet_site_service.assign_device_to_site(db, device, site, actor_user_id=seeded_users["admin"].id)
    device = fleet_site_service.assign_device_to_site(db, device, None, actor_user_id=seeded_users["admin"].id)
    assert device.site_id is None


def test_fleet_overview_counts_real_devices_only(db, org, active_device_factory):
    active_device_factory(device_identifier="ov-dev-1")
    active_device_factory(device_identifier="ov-dev-2")
    overview = fleet_analytics_service.fleet_overview(db, org.id)
    assert overview["total_devices"] == 2
    assert overview["administrative_status_counts"].get("active") == 2
    assert overview["baseline_assignment_pct"] == 0.0


def test_fleet_overview_tenant_isolation(db, org, active_device_factory, seeded_users):
    from app.models.organization import Organization

    other_org = Organization(name="Other Org", status="active")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)
    device_service.register_device(
        db, organization_id=other_org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="other-org-device", device_name="Other Device", device_type="field_sensor_node",
    )
    active_device_factory(device_identifier="own-org-device")

    overview = fleet_analytics_service.fleet_overview(db, org.id)
    assert overview["total_devices"] == 1  # the other org's device is never counted


def test_fleet_sites_api_crud_and_summary(client, tokens, auth_header):
    created = client.post("/api/v1/fleet/sites", json={"name": "API Site", "latitude": 10.0, "longitude": 20.0}, headers=auth_header(tokens, "analyst"))
    assert created.status_code == 201, created.text
    site_id = created.json()["id"]

    listed = client.get("/api/v1/fleet/sites", headers=auth_header(tokens, "viewer"))
    assert listed.status_code == 200
    assert any(s["id"] == site_id for s in listed.json())

    summary = client.get(f"/api/v1/fleet/sites/{site_id}/summary", headers=auth_header(tokens, "viewer"))
    assert summary.status_code == 200
    assert summary.json()["device_count"] == 0


def test_viewer_cannot_create_site(client, tokens, auth_header):
    resp = client.post("/api/v1/fleet/sites", json={"name": "nope"}, headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 403


def test_assign_device_site_via_api(client, tokens, auth_header, active_device_factory):
    device, _ = active_device_factory(device_identifier="site-api-dev-1")
    created = client.post("/api/v1/fleet/sites", json={"name": "Site via API"}, headers=auth_header(tokens, "analyst"))
    site_id = created.json()["id"]
    resp = client.post(f"/api/v1/devices/{device.id}/site", json={"site_id": site_id}, headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 200
    assert resp.json()["site_id"] == site_id


def test_fleet_overview_api(client, tokens, auth_header, active_device_factory):
    active_device_factory(device_identifier="ov-api-dev-1")
    resp = client.get("/api/v1/fleet/analytics/overview", headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_devices"] >= 1
    assert "presence_counts" in body
    assert "open_alerts_by_severity" in body
