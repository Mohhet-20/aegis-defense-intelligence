"""Unit tests for app/services/device_service.py:
registration/duplicate-identifier rejection, administrative lifecycle
transitions (including illegal ones), key rotation, authenticate_device's
gating on administrative_status, and the live-computed pending/conflict
counts."""
from __future__ import annotations

from datetime import datetime, timezone

from app.services import audit_service, device_service, edge_sync_service
from app.schemas.edge_sync import EDGE_SYNC_PROTOCOL_VERSION, SyncBatchRequest, SyncRecordEnvelope


def test_register_device_starts_pending_and_issues_one_time_key(db, org, seeded_users):
    device, api_key = device_service.register_device(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="dev-1", device_name="Device One", device_type="field_sensor_node",
    )
    assert device.administrative_status == "pending"
    assert device.api_key_hash is not None
    assert api_key.startswith("edge_")
    assert device.api_key_prefix == api_key[:10]


def test_register_device_rejects_duplicate_identifier_globally(db, org, seeded_users):
    device_service.register_device(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="dup-1", device_name="D1", device_type="field_sensor_node",
    )
    try:
        device_service.register_device(
            db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
            device_identifier="dup-1", device_name="D2", device_type="field_sensor_node",
        )
        assert False, "expected DuplicateDeviceIdentifierError"
    except device_service.DuplicateDeviceIdentifierError:
        pass


def test_pending_device_cannot_authenticate(db, org, seeded_users):
    device, api_key = device_service.register_device(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="pend-1", device_name="D", device_type="field_sensor_node",
    )
    assert device_service.authenticate_device(db, "pend-1", api_key) is None


def test_active_device_authenticates_and_updates_last_seen(db, org, seeded_users):
    device, api_key = device_service.register_device(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="act-1", device_name="D", device_type="field_sensor_node",
    )
    device_service.activate_device(db, device, actor_user_id=seeded_users["admin"].id)
    assert device.last_seen_at is None
    authed = device_service.authenticate_device(db, "act-1", api_key)
    assert authed is not None
    assert authed.last_seen_at is not None


def test_authenticate_device_rejects_wrong_key(db, org, seeded_users):
    device, api_key = device_service.register_device(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="wrongkey-1", device_name="D", device_type="field_sensor_node",
    )
    device_service.activate_device(db, device, actor_user_id=seeded_users["admin"].id)
    assert device_service.authenticate_device(db, "wrongkey-1", "not-the-real-key") is None


def test_suspend_then_reactivate(db, org, seeded_users):
    device, api_key = device_service.register_device(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="susp-1", device_name="D", device_type="field_sensor_node",
    )
    device_service.activate_device(db, device, actor_user_id=seeded_users["admin"].id)
    device_service.suspend_device(db, device, actor_user_id=seeded_users["admin"].id, reason="investigating")
    assert device.administrative_status == "suspended"
    assert device_service.authenticate_device(db, "susp-1", api_key) is None

    device_service.activate_device(db, device, actor_user_id=seeded_users["admin"].id)
    assert device.administrative_status == "active"
    assert device_service.authenticate_device(db, "susp-1", api_key) is not None


def test_revoke_is_terminal_and_invalidates_credential(db, org, seeded_users):
    device, api_key = device_service.register_device(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="rev-1", device_name="D", device_type="field_sensor_node",
    )
    device_service.activate_device(db, device, actor_user_id=seeded_users["admin"].id)
    device_service.revoke_device(db, device, actor_user_id=seeded_users["admin"].id, reason="decommissioned")
    assert device.administrative_status == "revoked"
    assert device.revoked_at is not None
    assert device.api_key_hash is None
    # even the correct plaintext key no longer verifies
    assert device_service.authenticate_device(db, "rev-1", api_key) is None

    for target in ("active", "suspended", "pending"):
        try:
            device_service.transition_administrative_status(db, device, new_status=target, actor_user_id=seeded_users["admin"].id)
            assert False, f"expected revoked -> {target} to be rejected"
        except device_service.InvalidDeviceLifecycleTransitionError:
            pass


def test_pending_cannot_be_suspended_directly(db, org, seeded_users):
    device, _ = device_service.register_device(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="pendsusp-1", device_name="D", device_type="field_sensor_node",
    )
    try:
        device_service.suspend_device(db, device, actor_user_id=seeded_users["admin"].id)
        assert False, "expected pending -> suspended to be rejected"
    except device_service.InvalidDeviceLifecycleTransitionError:
        pass


def test_rotate_api_key_invalidates_old_key(db, org, seeded_users):
    device, old_key = device_service.register_device(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="rot-1", device_name="D", device_type="field_sensor_node",
    )
    device_service.activate_device(db, device, actor_user_id=seeded_users["admin"].id)
    device, new_key = device_service.rotate_api_key(db, device, actor_user_id=seeded_users["admin"].id)
    assert new_key != old_key
    assert device_service.authenticate_device(db, "rot-1", old_key) is None
    assert device_service.authenticate_device(db, "rot-1", new_key) is not None


def test_rotate_api_key_rejected_on_revoked_device(db, org, seeded_users):
    device, _ = device_service.register_device(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="rotrev-1", device_name="D", device_type="field_sensor_node",
    )
    device_service.activate_device(db, device, actor_user_id=seeded_users["admin"].id)
    device_service.revoke_device(db, device, actor_user_id=seeded_users["admin"].id)
    try:
        device_service.rotate_api_key(db, device, actor_user_id=seeded_users["admin"].id)
        assert False, "expected rotation on a revoked device to be rejected"
    except device_service.InvalidDeviceLifecycleTransitionError:
        pass


def test_live_pending_sync_count_reflects_real_queue(db, org, active_device_factory):
    device, api_key = active_device_factory("pendcount-1")
    assert device_service.compute_pending_sync_count(db, org.id, device.id) == 0

    now = datetime.now(timezone.utc)
    envelope = SyncRecordEnvelope(
        message_id="m1", idempotency_key="k1", record_type="observation_capture", client_record_id="cr1",
        schema_version="v1", payload={"x": 1}, source_created_at=now, queued_at=now,
    )
    batch = SyncBatchRequest(protocol_version=EDGE_SYNC_PROTOCOL_VERSION, device_id=device.device_identifier, sent_at=now, records=[envelope])
    edge_sync_service.ingest_batch(db, device, batch)
    # the one record synced immediately -> no longer pending
    assert device_service.compute_pending_sync_count(db, org.id, device.id) == 0


def test_status_history_records_lifecycle_actions(db, org, seeded_users):
    device, _ = device_service.register_device(
        db, organization_id=org.id, actor_user_id=seeded_users["admin"].id,
        device_identifier="hist-1", device_name="D", device_type="field_sensor_node",
    )
    device_service.activate_device(db, device, actor_user_id=seeded_users["admin"].id, reason="go live")
    history = audit_service.list_for_target(db, org.id, target_type="device", target_id=device.id)
    actions = [h.action for h in history]
    assert "device.register" in actions
    assert "device.lifecycle_transition" in actions
