"""Unit tests for app/edge/local_store.py --
the device's own durable SQLite outbox. Exercises the state machine,
idempotency, retry classification, and -- the thing that actually
proves "durable" -- survival across a simulated process restart
(closing and reopening the same .db file)."""
from __future__ import annotations

import tempfile

import pytest

from app.edge.local_store import InvalidLocalTransitionError, LocalEdgeStore


@pytest.fixture()
def store():
    path = tempfile.mktemp(suffix=".db")
    s = LocalEdgeStore(path)
    yield s, path
    s.close()


def test_enqueue_persists_with_queued_status(store):
    s, _ = store
    row = s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1})
    assert row["local_status"] == "queued"
    assert row["retry_count"] == 0
    assert row["idempotency_key"]
    assert s.get(row["id"])["client_record_id"] == "cr1"


def test_idempotency_key_is_unique(store):
    s, _ = store
    s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1}, idempotency_key="same-key")
    with pytest.raises(Exception):
        s.enqueue(record_type="observation_capture", client_record_id="cr2", schema_version="v1", payload={"x": 2}, idempotency_key="same-key")


def test_mark_syncing_generates_fresh_message_id_each_attempt(store):
    s, _ = store
    row = s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1})
    first_message_id = row["message_id"]
    syncing = s.mark_syncing(row["id"])
    assert syncing["local_status"] == "syncing"
    assert syncing["message_id"] != first_message_id
    assert syncing["idempotency_key"] == row["idempotency_key"]  # never changes


def test_apply_ack_synced_is_terminal(store):
    s, _ = store
    row = s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1})
    s.mark_syncing(row["id"])
    acked = s.apply_ack(row["id"], sync_status="synced", sync_record_id="central-123")
    assert acked["local_status"] == "synced"
    assert acked["sync_record_id"] == "central-123"
    with pytest.raises(InvalidLocalTransitionError):
        s.apply_ack(row["id"], sync_status="queued")


def test_apply_ack_retryable_sets_backoff_from_retry_after(store):
    s, _ = store
    row = s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1})
    s.mark_syncing(row["id"])
    acked = s.apply_ack(row["id"], sync_status="retryable_failure", error_category="server_error", error_message="boom", retry_after_seconds=42)
    assert acked["local_status"] == "retryable_failure"
    assert acked["retry_count"] == 1
    assert acked["next_retry_at"] is not None


def test_mark_network_failure_classifies_and_backs_off(store):
    s, _ = store
    row = s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1})
    s.mark_syncing(row["id"])
    failed = s.mark_network_failure(row["id"], message="connection refused")
    assert failed["local_status"] == "retryable_failure"
    assert failed["last_error_category"] == "network"
    assert failed["next_retry_at"] is not None


def test_mark_auth_failure_is_permanent_never_auto_retried(store):
    s, _ = store
    row = s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1})
    s.mark_syncing(row["id"])
    failed = s.mark_auth_failure(row["id"], message="HTTP 401")
    assert failed["local_status"] == "permanent_failure"
    assert failed["last_error_category"] == "auth_failure"
    # list_ready_to_send never includes a permanent_failure row
    assert row["id"] not in [r["id"] for r in s.list_ready_to_send()]


def test_cancel_only_legal_from_queued_or_retryable(store):
    s, _ = store
    row = s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1})
    cancelled = s.cancel(row["id"])
    assert cancelled["local_status"] == "cancelled"

    row2 = s.enqueue(record_type="observation_capture", client_record_id="cr2", schema_version="v1", payload={"x": 2})
    s.mark_syncing(row2["id"])
    s.apply_ack(row2["id"], sync_status="synced")
    with pytest.raises(InvalidLocalTransitionError):
        s.cancel(row2["id"])


def test_list_ready_to_send_excludes_syncing_and_future_backoff(store):
    s, _ = store
    queued = s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1})
    syncing_row = s.enqueue(record_type="observation_capture", client_record_id="cr2", schema_version="v1", payload={"x": 2})
    s.mark_syncing(syncing_row["id"])
    backoff_row = s.enqueue(record_type="observation_capture", client_record_id="cr3", schema_version="v1", payload={"x": 3})
    s.mark_syncing(backoff_row["id"])
    s.apply_ack(backoff_row["id"], sync_status="retryable_failure", retry_after_seconds=3600)

    ready_ids = {r["id"] for r in s.list_ready_to_send()}
    assert queued["id"] in ready_ids
    assert syncing_row["id"] not in ready_ids
    assert backoff_row["id"] not in ready_ids  # not due yet


def test_recover_crashed_resets_stale_syncing_rows(store):
    s, _ = store
    row = s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1})
    s.mark_syncing(row["id"])
    s._conn.execute("UPDATE outbox SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (row["id"],))
    s._conn.commit()

    recovered = s.recover_crashed(stale_after_seconds=60)
    assert recovered == 1
    assert s.get(row["id"])["local_status"] == "retryable_failure"


def test_recover_crashed_ignores_fresh_syncing_rows(store):
    s, _ = store
    row = s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1})
    s.mark_syncing(row["id"])
    recovered = s.recover_crashed(stale_after_seconds=3600)
    assert recovered == 0
    assert s.get(row["id"])["local_status"] == "syncing"


def test_stats_counts_by_status(store):
    s, _ = store
    s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1})
    row2 = s.enqueue(record_type="observation_capture", client_record_id="cr2", schema_version="v1", payload={"x": 2})
    s.mark_syncing(row2["id"])
    s.apply_ack(row2["id"], sync_status="synced")

    stats = s.stats()
    assert stats["by_status"]["queued"] == 1
    assert stats["by_status"]["synced"] == 1
    assert stats["queue_depth"] == 1


def test_data_survives_reopening_the_same_db_file(store):
    s, path = store
    row = s.enqueue(record_type="observation_capture", client_record_id="cr1", schema_version="v1", payload={"x": 1})
    s.close()

    reopened = LocalEdgeStore(path)
    found = reopened.get(row["id"])
    assert found is not None
    assert found["client_record_id"] == "cr1"
    assert found["local_status"] == "queued"
    reopened.close()
