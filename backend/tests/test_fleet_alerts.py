"""Infrastructure alerting tests: generation,
deduplication, auto-resolution, and the ack/resolve/reopen lifecycle."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.services import fleet_alert_service


def _settings():
    return get_settings()


def test_offline_device_generates_a_critical_alert(db, active_device_factory):
    device, _ = active_device_factory(device_identifier="alert-dev-1")
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=_settings().FLEET_PRESENCE_OFFLINE_AFTER_SECONDS + 10)
    db.add(device)
    db.commit()
    alerts = fleet_alert_service.evaluate_alerts_for_device(db, device)
    assert any(a.alert_type == "device_offline" and a.severity == "critical" for a in alerts)


def test_repeated_evaluation_does_not_duplicate_the_open_alert(db, active_device_factory):
    device, _ = active_device_factory(device_identifier="alert-dev-2")
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=_settings().FLEET_PRESENCE_OFFLINE_AFTER_SECONDS + 10)
    db.add(device)
    db.commit()
    fleet_alert_service.evaluate_alerts_for_device(db, device)
    fleet_alert_service.evaluate_alerts_for_device(db, device)
    fleet_alert_service.evaluate_alerts_for_device(db, device)
    stmt = fleet_alert_service.list_alerts_query(device.organization_id, device_id=device.id, alert_type="device_offline")
    rows = list(db.execute(stmt).scalars().all())
    assert len(rows) == 1
    assert rows[0].occurrence_count == 3


def test_recovered_device_auto_resolves_its_offline_alert(db, active_device_factory):
    device, _ = active_device_factory(device_identifier="alert-dev-3")
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=_settings().FLEET_PRESENCE_OFFLINE_AFTER_SECONDS + 10)
    db.add(device)
    db.commit()
    fleet_alert_service.evaluate_alerts_for_device(db, device)

    device.last_seen_at = datetime.now(timezone.utc)
    db.add(device)
    db.commit()
    fleet_alert_service.evaluate_alerts_for_device(db, device)

    stmt = fleet_alert_service.list_alerts_query(device.organization_id, device_id=device.id, alert_type="device_offline")
    rows = list(db.execute(stmt).scalars().all())
    assert rows[0].status == "resolved"
    assert rows[0].resolution_note


def test_alert_dedup_key_recurs_as_a_new_row_after_resolution(db, active_device_factory):
    device, _ = active_device_factory(device_identifier="alert-dev-4")
    offline_at = datetime.now(timezone.utc) - timedelta(seconds=_settings().FLEET_PRESENCE_OFFLINE_AFTER_SECONDS + 10)
    device.last_seen_at = offline_at
    db.add(device)
    db.commit()
    fleet_alert_service.evaluate_alerts_for_device(db, device)

    device.last_seen_at = datetime.now(timezone.utc)
    db.add(device)
    db.commit()
    fleet_alert_service.evaluate_alerts_for_device(db, device)  # resolves it

    device.last_seen_at = offline_at
    db.add(device)
    db.commit()
    fleet_alert_service.evaluate_alerts_for_device(db, device)  # a new occurrence

    stmt = fleet_alert_service.list_alerts_query(device.organization_id, device_id=device.id, alert_type="device_offline")
    rows = list(db.execute(stmt).scalars().all())
    assert len(rows) == 2
    assert {r.status for r in rows} == {"resolved", "open"}


def test_acknowledge_resolve_reopen_lifecycle(db, active_device_factory, seeded_users):
    device, _ = active_device_factory(device_identifier="alert-dev-5")
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=_settings().FLEET_PRESENCE_OFFLINE_AFTER_SECONDS + 10)
    db.add(device)
    db.commit()
    alert = fleet_alert_service.evaluate_alerts_for_device(db, device)[0]

    alert = fleet_alert_service.acknowledge_alert(db, alert, actor_user_id=seeded_users["admin"].id, note="investigating")
    assert alert.status == "acknowledged"
    alert = fleet_alert_service.resolve_alert(db, alert, actor_user_id=seeded_users["admin"].id, note="fixed")
    assert alert.status == "resolved"

    # A resolved alert can no longer be acknowledged directly -- it must
    # be explicitly reopened first.
    with pytest.raises(fleet_alert_service.InvalidAlertTransitionError):
        fleet_alert_service.acknowledge_alert(db, alert, actor_user_id=seeded_users["admin"].id)

    alert = fleet_alert_service.reopen_alert(db, alert, actor_user_id=seeded_users["admin"].id, note="recurred")
    assert alert.status == "reopened"
    assert alert.occurrence_count == 2
    # A reopened alert can be acknowledged/resolved again, same as a
    # freshly-opened one.
    alert = fleet_alert_service.resolve_alert(db, alert, actor_user_id=seeded_users["admin"].id, note="fixed again")
    assert alert.status == "resolved"


def test_reopen_only_legal_from_resolved(db, active_device_factory, seeded_users):
    device, _ = active_device_factory(device_identifier="alert-dev-6")
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=_settings().FLEET_PRESENCE_OFFLINE_AFTER_SECONDS + 10)
    db.add(device)
    db.commit()
    alert = fleet_alert_service.evaluate_alerts_for_device(db, device)[0]
    with pytest.raises(fleet_alert_service.InvalidAlertTransitionError):
        fleet_alert_service.reopen_alert(db, alert, actor_user_id=seeded_users["admin"].id)


def test_alert_center_api_lists_and_acknowledges(client, tokens, auth_header, active_device_factory, db):
    device, _ = active_device_factory(device_identifier="alert-dev-7")
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=_settings().FLEET_PRESENCE_OFFLINE_AFTER_SECONDS + 10)
    db.add(device)
    db.commit()
    fleet_alert_service.evaluate_alerts_for_device(db, device)

    listed = client.get("/api/v1/fleet/alerts", headers=auth_header(tokens, "viewer"))
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    alert_id = next(i["id"] for i in listed.json()["items"] if i["device_id"] == device.id)

    forbidden = client.post(f"/api/v1/fleet/alerts/{alert_id}/acknowledge", json={}, headers=auth_header(tokens, "viewer"))
    assert forbidden.status_code == 403
    ok = client.post(f"/api/v1/fleet/alerts/{alert_id}/acknowledge", json={"note": "on it"}, headers=auth_header(tokens, "analyst"))
    assert ok.status_code == 200
    assert ok.json()["status"] == "acknowledged"


def test_sweep_raises_offline_alert_for_a_device_that_never_reported(client, tokens, auth_header, active_device_factory, db):
    """Correctness: a silent device makes no request of its own, so the
    inline evaluate-on-health-report path can never catch it -- only
    the explicit sweep can."""
    device, _ = active_device_factory(device_identifier="alert-dev-9")
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=_settings().FLEET_PRESENCE_OFFLINE_AFTER_SECONDS + 10)
    db.add(device)
    db.commit()

    stmt = fleet_alert_service.list_alerts_query(device.organization_id, device_id=device.id, alert_type="device_offline")
    assert list(db.execute(stmt).scalars().all()) == []  # nothing yet -- no request has been made

    resp = client.post("/api/v1/fleet/alerts/evaluate-sweep", headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["evaluated_device_count"] >= 1

    rows = list(db.execute(stmt).scalars().all())
    assert len(rows) == 1
    assert rows[0].status == "open"


def test_sweep_is_org_scoped(client, tokens, auth_header, active_device_factory, db, org, seeded_users):
    from app.models.organization import Organization
    from app.services import device_service

    other_org = Organization(name="Sweep Other Org", status="active")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)
    other_device, _ = device_service.register_device(
        db, organization_id=other_org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="sweep-other-org-dev", device_name="Other", device_type="field_sensor_node",
    )
    active_device_factory(device_identifier="sweep-own-org-dev")

    resp = client.post("/api/v1/fleet/alerts/evaluate-sweep", headers=auth_header(tokens, "analyst"))
    assert resp.status_code == 200
    # Only this org's devices are evaluated -- the other org's device is
    # never touched by this call.
    assert resp.json()["evaluated_device_count"] == 1


def test_viewer_cannot_trigger_sweep(client, tokens, auth_header):
    resp = client.post("/api/v1/fleet/alerts/evaluate-sweep", headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 403


def test_config_drift_alert_requires_evaluated_baseline(db, active_device_factory, org, seeded_users):
    """A device with no baseline assigned must never generate a
    config_drift alert from an unevaluated condition."""
    device, _ = active_device_factory(device_identifier="alert-dev-8")
    fleet_alert_service.evaluate_alerts_for_device(db, device)
    stmt = fleet_alert_service.list_alerts_query(device.organization_id, device_id=device.id, alert_type="config_drift")
    rows = list(db.execute(stmt).scalars().all())
    assert rows == []
