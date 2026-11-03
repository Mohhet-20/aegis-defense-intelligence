"""Administrative lifecycle extension tests:
maintenance/decommissioned states and the confirmation-preview endpoint."""
from __future__ import annotations

from app.services import audit_service, device_service


def test_maintenance_only_legal_from_active(db, active_device_factory, seeded_users):
    # active_device_factory already activates the device.
    device, _ = active_device_factory(device_identifier="life-dev-1")
    device = device_service.enter_maintenance(db, device, actor_user_id=seeded_users["admin"].id, reason="scheduled battery swap")
    assert device.administrative_status == "maintenance"
    device = device_service.activate_device(db, device, actor_user_id=seeded_users["admin"].id)
    assert device.administrative_status == "active"


def test_decommission_preserves_historical_rows_and_blocks_reactivation(db, active_device_factory, seeded_users):
    device, _ = active_device_factory(device_identifier="life-dev-2")
    device = device_service.decommission_device(db, device, actor_user_id=seeded_users["admin"].id, reason="end of life")
    assert device.administrative_status == "decommissioned"
    history = audit_service.list_for_target(db, device.organization_id, target_type="device", target_id=device.id)
    assert any(h.action == "device.register" for h in history)
    assert any(h.action == "device.lifecycle_transition" for h in history)

    import pytest

    with pytest.raises(device_service.InvalidDeviceLifecycleTransitionError):
        device_service.activate_device(db, device, actor_user_id=seeded_users["admin"].id)
    # revoke is still legal from decommissioned
    device = device_service.revoke_device(db, device, actor_user_id=seeded_users["admin"].id)
    assert device.administrative_status == "revoked"


def test_maintenance_is_distinct_from_suspended(db, active_device_factory, seeded_users):
    device, _ = active_device_factory(device_identifier="life-dev-3")
    device = device_service.suspend_device(db, device, actor_user_id=seeded_users["admin"].id, reason="credential concern")
    assert device.administrative_status == "suspended"
    import pytest

    with pytest.raises(device_service.InvalidDeviceLifecycleTransitionError):
        device_service.decommission_device(db, device, actor_user_id=seeded_users["admin"].id)


def test_lifecycle_preview_is_read_only_and_reports_impact(db, active_device_factory, seeded_users):
    device, _ = active_device_factory(device_identifier="life-dev-4")
    preview = device_service.preview_lifecycle_transition(db, device, new_status="decommissioned")
    assert preview["is_legal"] is True
    assert preview["is_consequential"] is True
    assert preview["impact_notes"]
    # No change actually made.
    assert device.administrative_status == "active"


def test_lifecycle_preview_illegal_transition(db, active_device_factory):
    device, _ = active_device_factory(device_identifier="life-dev-5")
    preview = device_service.preview_lifecycle_transition(db, device, new_status="pending")
    assert preview["is_legal"] is False


def test_lifecycle_preview_api(client, tokens, auth_header, active_device_factory):
    device, _ = active_device_factory(device_identifier="life-dev-6")
    resp = client.get(f"/api/v1/devices/{device.id}/lifecycle-preview", params={"target_status": "decommissioned"}, headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 200
    assert resp.json()["is_consequential"] is True


def test_maintenance_and_decommission_via_api(client, tokens, auth_header, active_device_factory):
    device, _ = active_device_factory(device_identifier="life-dev-7")
    maint = client.post(f"/api/v1/devices/{device.id}/maintenance", json={"reason": "firmware update"}, headers=auth_header(tokens, "analyst"))
    assert maint.status_code == 200
    assert maint.json()["administrative_status"] == "maintenance"
    decom = client.post(f"/api/v1/devices/{device.id}/decommission", json={"reason": "retired"}, headers=auth_header(tokens, "analyst"))
    assert decom.status_code == 200
    assert decom.json()["administrative_status"] == "decommissioned"


def test_viewer_cannot_enter_maintenance_or_decommission(client, tokens, auth_header, active_device_factory):
    device, _ = active_device_factory(device_identifier="life-dev-8")
    resp = client.post(f"/api/v1/devices/{device.id}/maintenance", json={}, headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 403
    resp = client.post(f"/api/v1/devices/{device.id}/decommission", json={}, headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 403
