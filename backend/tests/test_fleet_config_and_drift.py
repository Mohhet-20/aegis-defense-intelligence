"""Device configuration baseline / optimistic-concurrency / drift tests."""
from __future__ import annotations

from app.services import fleet_config_service


def test_drift_not_evaluated_without_a_baseline(db, active_device_factory):
    """A missing baseline is not an absence of drift -- `evaluated`
    must be False, `has_drift` must be None, never a fabricated
    "no drift" True/False."""
    device, _ = active_device_factory(device_identifier="cfg-dev-1")
    drift = fleet_config_service.compute_drift(db, device)
    assert drift["evaluated"] is False
    assert drift["has_drift"] is None


def test_drift_detected_against_assigned_baseline(db, active_device_factory, org, seeded_users):
    device, _ = active_device_factory(device_identifier="cfg-dev-2")
    baseline = fleet_config_service.create_baseline(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id, name="standard-v1",
        expected_config={"sample_rate_hz": 10, "mode": "patrol"},
    )
    device = fleet_config_service.assign_baseline(db, device, baseline, actor_user_id=seeded_users["admin"].id)
    device = fleet_config_service.update_config(
        db, device, new_config={"sample_rate_hz": 5, "mode": "patrol"}, expected_revision=0, actor_user_id=seeded_users["admin"].id,
    )
    drift = fleet_config_service.compute_drift(db, device)
    assert drift["evaluated"] is True
    assert drift["has_drift"] is True
    assert {"key": "sample_rate_hz", "current_value": 5, "expected_value": 10} in drift["differences"]


def test_config_matches_baseline_no_drift(db, active_device_factory, org, seeded_users):
    device, _ = active_device_factory(device_identifier="cfg-dev-3")
    baseline = fleet_config_service.create_baseline(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id, name="standard-v2", expected_config={"mode": "patrol"},
    )
    device = fleet_config_service.assign_baseline(db, device, baseline, actor_user_id=seeded_users["admin"].id)
    device = fleet_config_service.update_config(db, device, new_config={"mode": "patrol"}, expected_revision=0, actor_user_id=seeded_users["admin"].id)
    drift = fleet_config_service.compute_drift(db, device)
    assert drift == {"evaluated": True, "has_drift": False, "baseline_id": baseline.id, "baseline_version": baseline.version, "differences": []}


def test_optimistic_concurrency_rejects_stale_revision(db, active_device_factory, seeded_users):
    device, _ = active_device_factory(device_identifier="cfg-dev-4")
    fleet_config_service.update_config(db, device, new_config={"a": 1}, expected_revision=0, actor_user_id=seeded_users["admin"].id)
    import pytest

    with pytest.raises(fleet_config_service.ConfigRevisionConflictError):
        fleet_config_service.update_config(db, device, new_config={"a": 2}, expected_revision=0, actor_user_id=seeded_users["admin"].id)
    # the correct current revision (1) succeeds
    device = fleet_config_service.update_config(db, device, new_config={"a": 2}, expected_revision=1, actor_user_id=seeded_users["admin"].id)
    assert device.config_revision == 2
    assert device.current_config == {"a": 2}


def test_device_config_api_revision_conflict_returns_409(client, tokens, auth_header, active_device_factory):
    device, _ = active_device_factory(device_identifier="cfg-dev-5")
    first = client.put(f"/api/v1/devices/{device.id}/config", json={"new_config": {"a": 1}, "expected_revision": 0}, headers=auth_header(tokens, "analyst"))
    assert first.status_code == 200, first.text
    conflict = client.put(f"/api/v1/devices/{device.id}/config", json={"new_config": {"a": 2}, "expected_revision": 0}, headers=auth_header(tokens, "analyst"))
    assert conflict.status_code == 409


def test_baseline_assignment_and_drift_via_api(client, tokens, auth_header, active_device_factory):
    device, _ = active_device_factory(device_identifier="cfg-dev-6")
    created = client.post(
        "/api/v1/fleet/config-baselines", json={"name": "api-baseline", "expected_config": {"x": 1}},
        headers=auth_header(tokens, "analyst"),
    )
    assert created.status_code == 201, created.text
    baseline_id = created.json()["id"]
    assigned = client.post(f"/api/v1/devices/{device.id}/config/baseline", json={"baseline_id": baseline_id}, headers=auth_header(tokens, "analyst"))
    assert assigned.status_code == 200
    assert assigned.json()["drift"]["evaluated"] is True
    assert assigned.json()["drift"]["has_drift"] is True  # device.current_config starts {}

    updated = client.put(f"/api/v1/devices/{device.id}/config", json={"new_config": {"x": 1}, "expected_revision": 0}, headers=auth_header(tokens, "analyst"))
    assert updated.status_code == 200
    assert updated.json()["drift"]["has_drift"] is False


def test_viewer_cannot_create_baseline_or_update_config(client, tokens, auth_header, active_device_factory):
    device, _ = active_device_factory(device_identifier="cfg-dev-7")
    resp = client.post("/api/v1/fleet/config-baselines", json={"name": "x", "expected_config": {}}, headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 403
    resp = client.put(f"/api/v1/devices/{device.id}/config", json={"new_config": {}, "expected_revision": 0}, headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 403
