"""Unit tests for app/services/edge_sync_service.py (Phase 8, Sections
5-9): idempotent batch ingestion, the two-tier conflict policy
(immutable quarantine / mutable revision-conflict), the explicit state
machine + its transition enforcement, retry/backoff, crash recovery,
and protocol-version rejection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import OperationalError

from app.models.sync_record import SYNC_RECORD_TRANSITIONS
from app.schemas.edge_sync import EDGE_SYNC_PROTOCOL_VERSION, SyncBatchRequest, SyncRecordEnvelope
from app.services import edge_conflict_service, edge_sync_service


def _envelope(**overrides) -> SyncRecordEnvelope:
    now = datetime.now(timezone.utc)
    defaults = dict(
        message_id="m1", idempotency_key="k1", record_type="observation_capture", client_record_id="cr1",
        schema_version="v1", payload={"x": 1}, source_created_at=now, queued_at=now,
    )
    defaults.update(overrides)
    return SyncRecordEnvelope(**defaults)


def _batch(records, **overrides) -> SyncBatchRequest:
    now = datetime.now(timezone.utc)
    defaults = dict(protocol_version=EDGE_SYNC_PROTOCOL_VERSION, device_id="dev", sent_at=now, records=records)
    defaults.update(overrides)
    return SyncBatchRequest(**defaults)


def test_new_immutable_record_is_accepted_synced(db, active_device_factory):
    device, _ = active_device_factory()
    resp = edge_sync_service.ingest_batch(db, device, _batch([_envelope()], device_id=device.device_identifier))
    assert resp.accepted_count == 1
    assert resp.results[0].sync_status == "synced"


def test_resubmitting_same_idempotency_key_is_a_no_op(db, active_device_factory):
    device, _ = active_device_factory()
    batch = _batch([_envelope()], device_id=device.device_identifier)
    first = edge_sync_service.ingest_batch(db, device, batch)
    second = edge_sync_service.ingest_batch(db, device, batch)
    assert first.results[0].sync_record_id == second.results[0].sync_record_id
    assert second.results[0].sync_status == "synced"


def test_duplicate_client_record_id_same_hash_is_idempotent_not_quarantined(db, active_device_factory):
    device, _ = active_device_factory()
    env1 = _envelope(message_id="m1", idempotency_key="k1", client_record_id="cr-dup", payload={"x": 1})
    env2 = _envelope(message_id="m2", idempotency_key="k2", client_record_id="cr-dup", payload={"x": 1})
    edge_sync_service.ingest_batch(db, device, _batch([env1], device_id=device.device_identifier))
    resp = edge_sync_service.ingest_batch(db, device, _batch([env2], device_id=device.device_identifier))
    assert resp.results[0].sync_status == "synced"


def test_duplicate_client_record_id_different_payload_is_quarantined(db, active_device_factory):
    device, _ = active_device_factory()
    env1 = _envelope(message_id="m1", idempotency_key="k1", client_record_id="cr-conflict", payload={"x": 1})
    env2 = _envelope(message_id="m2", idempotency_key="k2", client_record_id="cr-conflict", payload={"x": 2})
    edge_sync_service.ingest_batch(db, device, _batch([env1], device_id=device.device_identifier))
    resp = edge_sync_service.ingest_batch(db, device, _batch([env2], device_id=device.device_identifier))
    assert resp.results[0].sync_status == "quarantined"
    assert resp.results[0].error_category == "integrity_failure"
    assert resp.quarantined_count == 1


def test_unknown_record_type_is_quarantined_validation_error(db, active_device_factory):
    device, _ = active_device_factory()
    env = SyncRecordEnvelope.model_construct(
        message_id="m1", idempotency_key="k1", record_type="not_a_real_type", client_record_id="cr1",
        schema_version="v1", payload={"x": 1}, source_created_at=datetime.now(timezone.utc), queued_at=datetime.now(timezone.utc), base_revision=None,
    )
    resp = edge_sync_service.ingest_batch(db, device, _batch([env], device_id=device.device_identifier))
    assert resp.results[0].sync_status == "quarantined"
    assert resp.results[0].error_category == "validation_error"


def test_oversized_payload_is_quarantined(db, active_device_factory, monkeypatch):
    device, _ = active_device_factory()
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "EDGE_SYNC_MAX_PAYLOAD_BYTES", 10)
    env = _envelope(payload={"a_very_long_key_that_blows_the_tiny_limit": "x" * 50})
    resp = edge_sync_service.ingest_batch(db, device, _batch([env], device_id=device.device_identifier))
    assert resp.results[0].sync_status == "quarantined"
    assert resp.results[0].error_category == "validation_error"


def test_mutable_record_first_submission_requires_base_revision(db, active_device_factory):
    device, _ = active_device_factory()
    env = _envelope(record_type="annotation", client_record_id="ann1", base_revision=None)
    resp = edge_sync_service.ingest_batch(db, device, _batch([env], device_id=device.device_identifier))
    assert resp.results[0].sync_status == "quarantined"
    assert resp.results[0].error_category == "validation_error"


def test_mutable_record_accepted_when_base_revision_matches(db, active_device_factory):
    device, _ = active_device_factory()
    env = _envelope(record_type="annotation", client_record_id="ann1", base_revision=0, payload={"text": "v1"})
    resp = edge_sync_service.ingest_batch(db, device, _batch([env], device_id=device.device_identifier))
    assert resp.results[0].sync_status == "synced"
    record = edge_sync_service.get_sync_record(db, device.organization_id, resp.results[0].sync_record_id)
    assert record.revision == 1


def test_mutable_record_stale_base_revision_creates_conflict_never_overwrites(db, active_device_factory):
    device, _ = active_device_factory()
    env1 = _envelope(message_id="m1", idempotency_key="k1", record_type="annotation", client_record_id="ann1", base_revision=0, payload={"text": "v1"})
    edge_sync_service.ingest_batch(db, device, _batch([env1], device_id=device.device_identifier))

    env2 = _envelope(message_id="m2", idempotency_key="k2", record_type="annotation", client_record_id="ann1", base_revision=0, payload={"text": "stale edit"})
    resp = edge_sync_service.ingest_batch(db, device, _batch([env2], device_id=device.device_identifier))
    assert resp.results[0].sync_status == "conflict"
    assert resp.conflict_count == 1
    assert resp.results[0].conflict_id is not None

    conflict = edge_conflict_service.get_conflict(db, device.organization_id, resp.results[0].conflict_id)
    assert conflict.conflict_reason == "revision_mismatch"
    assert conflict.resolution_status == "unresolved"
    assert conflict.local_version["payload"] == {"text": "stale edit"}
    assert conflict.central_version["payload"] == {"text": "v1"}

    # the CENTRAL record was never silently overwritten -- it's still v1
    current = edge_sync_service._get_current_accepted(db, device.organization_id, "annotation", "ann1")
    assert current.payload == {"text": "v1"}


def test_second_edit_with_correct_base_revision_succeeds(db, active_device_factory):
    device, _ = active_device_factory()
    env1 = _envelope(message_id="m1", idempotency_key="k1", record_type="annotation", client_record_id="ann1", base_revision=0, payload={"text": "v1"})
    edge_sync_service.ingest_batch(db, device, _batch([env1], device_id=device.device_identifier))

    env2 = _envelope(message_id="m2", idempotency_key="k2", record_type="annotation", client_record_id="ann1", base_revision=1, payload={"text": "v2"})
    resp = edge_sync_service.ingest_batch(db, device, _batch([env2], device_id=device.device_identifier))
    assert resp.results[0].sync_status == "synced"
    record = edge_sync_service.get_sync_record(db, device.organization_id, resp.results[0].sync_record_id)
    assert record.revision == 2
    assert record.supersedes_sync_record_id is not None


def test_unsupported_protocol_version_rejects_whole_batch(db, active_device_factory):
    device, _ = active_device_factory()
    batch = _batch([_envelope()], device_id=device.device_identifier, protocol_version="edge_sync_v99")
    with pytest.raises(edge_sync_service.UnsupportedProtocolVersionError):
        edge_sync_service.ingest_batch(db, device, batch)


def test_batch_too_large_is_rejected(db, active_device_factory, monkeypatch):
    device, _ = active_device_factory()
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "EDGE_SYNC_MAX_BATCH_SIZE", 1)
    envelopes = [_envelope(message_id=f"m{i}", idempotency_key=f"k{i}", client_record_id=f"cr{i}") for i in range(2)]
    with pytest.raises(edge_sync_service.BatchTooLargeError):
        edge_sync_service.ingest_batch(db, device, _batch(envelopes, device_id=device.device_identifier))


def test_transition_table_rejects_illegal_transition():
    record = type("Fake", (), {"sync_status": "synced"})()
    with pytest.raises(edge_sync_service.InvalidSyncTransitionError):
        edge_sync_service._transition(record, "queued")


def test_all_documented_states_appear_in_transition_table():
    from app.models.sync_record import SYNC_RECORD_STATUSES

    assert set(SYNC_RECORD_TRANSITIONS.keys()) == set(SYNC_RECORD_STATUSES)


def test_compute_backoff_seconds_is_bounded_and_deterministic_with_no_jitter(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "EDGE_SYNC_RETRY_BASE_DELAY_SECONDS", 2.0)
    monkeypatch.setattr(settings, "EDGE_SYNC_RETRY_MAX_DELAY_SECONDS", 100.0)
    monkeypatch.setattr(settings, "EDGE_SYNC_RETRY_JITTER_FRACTION", 0.0)
    assert edge_sync_service.compute_backoff_seconds(0, settings) == 2.0
    assert edge_sync_service.compute_backoff_seconds(1, settings) == 4.0
    assert edge_sync_service.compute_backoff_seconds(2, settings) == 8.0
    # bounded -- never exceeds the configured max even at a huge retry_count
    assert edge_sync_service.compute_backoff_seconds(50, settings) == 100.0


def test_a_transient_server_error_during_acceptance_is_retried_with_backoff(db, active_device_factory, monkeypatch):
    device, _ = active_device_factory()
    env = _envelope()

    original_commit = db.commit
    call_count = {"n": 0}

    def flaky_commit():
        call_count["n"] += 1
        # Fail exactly the 3rd commit of this ingest_batch call (1:
        # _get_or_create_record's insert, 2: the queued->syncing
        # transition, 3: _accept_immutable's final commit) -- simulates
        # a genuine transient DB error (e.g. "database is locked") at
        # the moment the record would have become durably synced.
        if call_count["n"] == 3:
            raise OperationalError("database is locked", {}, Exception("locked"))
        return original_commit()

    monkeypatch.setattr(db, "commit", flaky_commit)
    resp = edge_sync_service.ingest_batch(db, device, _batch([env], device_id=device.device_identifier))
    assert resp.results[0].sync_status == "retryable_failure"
    assert resp.results[0].error_category == "server_error"
    assert resp.results[0].retry_after_seconds is not None

    record = edge_sync_service.get_sync_record(db, device.organization_id, resp.results[0].sync_record_id)
    assert record.retry_count == 1
    assert record.next_retry_at is not None


def test_resubmission_of_retryable_failure_reprocesses_and_can_succeed(db, active_device_factory):
    device, _ = active_device_factory()
    env = _envelope()
    record, is_new = edge_sync_service._get_or_create_record(db, device, None, env)
    edge_sync_service._commit_transition(db, record, "syncing")
    edge_sync_service._commit_transition(db, record, "retryable_failure", retry_count=1, last_error_category="server_error", last_error_message="injected")

    resp = edge_sync_service.ingest_batch(db, device, _batch([env], device_id=device.device_identifier))
    assert resp.results[0].sync_status == "synced"
    assert resp.results[0].sync_record_id == record.id


def test_max_retry_count_exceeded_goes_permanent_failure(db, active_device_factory, monkeypatch):
    device, _ = active_device_factory()
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "EDGE_SYNC_MAX_RETRY_COUNT", 1)
    env = _envelope()
    record, _ = edge_sync_service._get_or_create_record(db, device, None, env)
    edge_sync_service._commit_transition(db, record, "syncing")
    edge_sync_service._commit_transition(db, record, "retryable_failure", retry_count=1, last_error_category="server_error")

    resp = edge_sync_service.ingest_batch(db, device, _batch([env], device_id=device.device_identifier))
    assert resp.results[0].sync_status == "permanent_failure"


def test_cancel_sync_record_rejected_once_synced(db, active_device_factory):
    device, _ = active_device_factory()
    resp = edge_sync_service.ingest_batch(db, device, _batch([_envelope()], device_id=device.device_identifier))
    record = edge_sync_service.get_sync_record(db, device.organization_id, resp.results[0].sync_record_id)
    with pytest.raises(edge_sync_service.InvalidSyncTransitionError):
        edge_sync_service.cancel_sync_record(db, record, actor_user_id="someone")


def test_cancel_sync_record_succeeds_while_queued(db, active_device_factory):
    device, _ = active_device_factory()
    env = _envelope()
    record, _ = edge_sync_service._get_or_create_record(db, device, None, env)
    cancelled = edge_sync_service.cancel_sync_record(db, record, actor_user_id="someone", reason="operator cancelled")
    assert cancelled.sync_status == "cancelled"


def test_force_retry_on_permanent_failure_resets_retry_count(db, active_device_factory):
    device, _ = active_device_factory()
    env = _envelope()
    record, _ = edge_sync_service._get_or_create_record(db, device, None, env)
    edge_sync_service._commit_transition(db, record, "syncing")
    edge_sync_service._commit_transition(db, record, "permanent_failure", retry_count=5, last_error_category="server_error")

    retried = edge_sync_service.force_retry_sync_record(db, record, actor_user_id="someone")
    assert retried.sync_status == "synced"
    assert retried.retry_count == 0


def test_force_retry_rejected_on_synced_record(db, active_device_factory):
    device, _ = active_device_factory()
    resp = edge_sync_service.ingest_batch(db, device, _batch([_envelope()], device_id=device.device_identifier))
    record = edge_sync_service.get_sync_record(db, device.organization_id, resp.results[0].sync_record_id)
    with pytest.raises(edge_sync_service.InvalidSyncTransitionError):
        edge_sync_service.force_retry_sync_record(db, record, actor_user_id="someone")


def test_recover_stale_syncing_records_only_touches_truly_stale_rows(db, active_device_factory):
    device, _ = active_device_factory()
    env = _envelope()
    record, _ = edge_sync_service._get_or_create_record(db, device, None, env)
    edge_sync_service._commit_transition(db, record, "syncing")
    db.execute(
        __import__("sqlalchemy").text("UPDATE sync_records SET updated_at = :ts WHERE id = :id"),
        {"ts": datetime(2000, 1, 1, tzinfo=timezone.utc), "id": record.id},
    )
    db.commit()

    recovered = edge_sync_service.recover_stale_syncing_records(db, organization_id=device.organization_id)
    assert recovered == 1
    db.refresh(record)
    assert record.sync_status == "retryable_failure"


def test_get_queue_summary_reflects_real_counts(db, active_device_factory):
    device, _ = active_device_factory()
    edge_sync_service.ingest_batch(db, device, _batch([_envelope()], device_id=device.device_identifier))
    summary = edge_sync_service.get_queue_summary(db, device.organization_id)
    assert summary["total_records"] == 1
    assert any(row["sync_status"] == "synced" and row["count"] == 1 for row in summary["by_status"])
    assert summary["quarantined_count"] == 0
    assert summary["unresolved_conflict_count"] == 0
