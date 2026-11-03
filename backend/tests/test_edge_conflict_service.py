"""Unit tests for app/services/edge_conflict_service.py (Phase 8,
Section 8.4): each resolution strategy's effect on the conflicting
SyncRecord, the already-resolved guard, and the invalid-strategy
guard. Never resolved merely because a record arrived later -- every
test here resolves through an explicit, audited call."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas.edge_sync import EDGE_SYNC_PROTOCOL_VERSION, SyncBatchRequest, SyncRecordEnvelope
from app.services import audit_service, edge_conflict_service, edge_sync_service


def _make_conflict(db, device):
    now = datetime.now(timezone.utc)
    env1 = SyncRecordEnvelope(
        message_id="m1", idempotency_key="k1", record_type="annotation", client_record_id="ann1",
        schema_version="v1", payload={"text": "central version"}, source_created_at=now, queued_at=now, base_revision=0,
    )
    batch1 = SyncBatchRequest(protocol_version=EDGE_SYNC_PROTOCOL_VERSION, device_id=device.device_identifier, sent_at=now, records=[env1])
    edge_sync_service.ingest_batch(db, device, batch1)

    env2 = SyncRecordEnvelope(
        message_id="m2", idempotency_key="k2", record_type="annotation", client_record_id="ann1",
        schema_version="v1", payload={"text": "local stale edit"}, source_created_at=now, queued_at=now, base_revision=0,
    )
    batch2 = SyncBatchRequest(protocol_version=EDGE_SYNC_PROTOCOL_VERSION, device_id=device.device_identifier, sent_at=now, records=[env2])
    resp = edge_sync_service.ingest_batch(db, device, batch2)
    conflict_id = resp.results[0].conflict_id
    sync_record_id = resp.results[0].sync_record_id
    return conflict_id, sync_record_id


def test_resolve_keep_central_discards_device_submission(db, active_device_factory, seeded_users):
    device, _ = active_device_factory()
    conflict_id, sync_record_id = _make_conflict(db, device)
    conflict = edge_conflict_service.get_conflict(db, device.organization_id, conflict_id)

    resolved = edge_conflict_service.resolve_conflict(db, conflict, resolution_strategy="keep_central", actor_user_id=seeded_users["admin"].id)
    assert resolved.resolution_status == "resolved"
    assert resolved.resolution_strategy == "keep_central"

    record = edge_sync_service.get_sync_record(db, device.organization_id, sync_record_id)
    assert record.sync_status == "permanent_failure"
    current = edge_sync_service._get_current_accepted(db, device.organization_id, "annotation", "ann1")
    assert current.payload == {"text": "central version"}


def test_resolve_keep_local_promotes_device_submission(db, active_device_factory, seeded_users):
    device, _ = active_device_factory()
    conflict_id, sync_record_id = _make_conflict(db, device)
    conflict = edge_conflict_service.get_conflict(db, device.organization_id, conflict_id)

    edge_conflict_service.resolve_conflict(db, conflict, resolution_strategy="keep_local", actor_user_id=seeded_users["admin"].id)

    record = edge_sync_service.get_sync_record(db, device.organization_id, sync_record_id)
    assert record.sync_status == "synced"
    assert record.revision == 2
    current = edge_sync_service._get_current_accepted(db, device.organization_id, "annotation", "ann1")
    assert current.id == record.id
    assert current.payload == {"text": "local stale edit"}


def test_resolve_merged_never_takes_device_payload_verbatim(db, active_device_factory, seeded_users):
    device, _ = active_device_factory()
    conflict_id, sync_record_id = _make_conflict(db, device)
    conflict = edge_conflict_service.get_conflict(db, device.organization_id, conflict_id)

    edge_conflict_service.resolve_conflict(
        db, conflict, resolution_strategy="merged", actor_user_id=seeded_users["admin"].id, resolution_note="combined both edits by hand",
    )
    record = edge_sync_service.get_sync_record(db, device.organization_id, sync_record_id)
    # "merged" means a human composed the outcome externally -- the
    # conflicting record's own submitted payload is never silently
    # promoted, so it stays non-authoritative.
    assert record.sync_status == "permanent_failure"
    current = edge_sync_service._get_current_accepted(db, device.organization_id, "annotation", "ann1")
    assert current.payload == {"text": "central version"}


def test_cannot_resolve_an_already_resolved_conflict(db, active_device_factory, seeded_users):
    device, _ = active_device_factory()
    conflict_id, _ = _make_conflict(db, device)
    conflict = edge_conflict_service.get_conflict(db, device.organization_id, conflict_id)
    edge_conflict_service.resolve_conflict(db, conflict, resolution_strategy="keep_central", actor_user_id=seeded_users["admin"].id)

    with pytest.raises(edge_conflict_service.ConflictAlreadyResolvedError):
        edge_conflict_service.resolve_conflict(db, conflict, resolution_strategy="keep_local", actor_user_id=seeded_users["admin"].id)


def test_rejects_invalid_resolution_strategy(db, active_device_factory, seeded_users):
    device, _ = active_device_factory()
    conflict_id, _ = _make_conflict(db, device)
    conflict = edge_conflict_service.get_conflict(db, device.organization_id, conflict_id)
    with pytest.raises(edge_conflict_service.InvalidConflictResolutionError):
        edge_conflict_service.resolve_conflict(db, conflict, resolution_strategy="last_write_wins", actor_user_id=seeded_users["admin"].id)


def test_resolution_is_fully_audited(db, active_device_factory, seeded_users):
    device, _ = active_device_factory()
    conflict_id, _ = _make_conflict(db, device)
    conflict = edge_conflict_service.get_conflict(db, device.organization_id, conflict_id)
    edge_conflict_service.resolve_conflict(db, conflict, resolution_strategy="keep_central", actor_user_id=seeded_users["admin"].id, resolution_note="reviewed and confirmed")

    history = audit_service.list_for_target(db, device.organization_id, target_type="sync_conflict", target_id=conflict_id)
    actions = [h.action for h in history]
    assert "edge_conflict.resolve" in actions


def test_list_conflicts_query_filters_by_resolution_status(db, active_device_factory, seeded_users):
    device, _ = active_device_factory()
    conflict_id, _ = _make_conflict(db, device)

    unresolved = list(db.execute(edge_conflict_service.list_conflicts_query(device.organization_id, resolution_status="unresolved")).scalars())
    assert len(unresolved) == 1

    conflict = edge_conflict_service.get_conflict(db, device.organization_id, conflict_id)
    edge_conflict_service.resolve_conflict(db, conflict, resolution_strategy="keep_central", actor_user_id=seeded_users["admin"].id)

    unresolved_after = list(db.execute(edge_conflict_service.list_conflicts_query(device.organization_id, resolution_status="unresolved")).scalars())
    assert len(unresolved_after) == 0
