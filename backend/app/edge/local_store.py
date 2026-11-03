"""The device's own durable local outbox (Phase 8, Section 4: "offline-
first local persistence appropriate to the actual architecture"). Raw
`sqlite3` against its OWN separate `.db` file -- deliberately NOT the
central app's SQLAlchemy session/engine, so "local vs. central
ownership" is a real architectural boundary a test can actually
exercise (kill the process, reopen the same file, prove nothing was
lost), not just a documented intention.

Reuses the exact same state vocabulary and transition table as the
central `SyncRecord` (`app.models.sync_record.SYNC_RECORD_STATUSES`/
`SYNC_RECORD_TRANSITIONS`) -- Section 6 describes ONE documented state
machine, and this is deliberately the same one, enforced the same way,
on the other end of the sync protocol. A row here is never deleted on
mere HTTP-request-initiation; only `mark_synced`/`mark_cancelled`
retire a row from the pending set, and even then the row is kept
(not deleted) as local history until explicitly purged.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.sync_record import SYNC_RECORD_TRANSITIONS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    message_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    client_record_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    payload TEXT NOT NULL,
    payload_hash TEXT,
    base_revision INTEGER,
    source_created_at TEXT NOT NULL,
    queued_at TEXT NOT NULL,
    local_status TEXT NOT NULL DEFAULT 'queued',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    last_error_category TEXT,
    last_error_message TEXT,
    sync_record_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbox_local_status ON outbox(local_status);
"""


class InvalidLocalTransitionError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


class LocalEdgeStore:
    """One instance per device (per `.db` file). Safe to open, close,
    and reopen against the same file across process restarts -- that
    round trip is exactly what proves durability."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- writes ----------------------------------------------------

    def enqueue(
        self, *, record_type: str, client_record_id: str, schema_version: str, payload: dict,
        base_revision: Optional[int] = None, payload_hash: Optional[str] = None, idempotency_key: Optional[str] = None,
    ) -> dict:
        """Durably persists one locally-captured logical record in
        `queued` status. Commits immediately -- a capture is never held
        only in memory."""
        row_id = str(uuid.uuid4())
        now = _now_iso()
        record = {
            "id": row_id,
            "idempotency_key": idempotency_key or str(uuid.uuid4()),
            "message_id": str(uuid.uuid4()),
            "record_type": record_type,
            "client_record_id": client_record_id,
            "schema_version": schema_version,
            "payload": json.dumps(payload),
            "payload_hash": payload_hash,
            "base_revision": base_revision,
            "source_created_at": now,
            "queued_at": now,
            "local_status": "queued",
            "retry_count": 0,
            "next_retry_at": None,
            "last_error_category": None,
            "last_error_message": None,
            "sync_record_id": None,
            "created_at": now,
            "updated_at": now,
        }
        self._conn.execute(
            "INSERT INTO outbox (id, idempotency_key, message_id, record_type, client_record_id, schema_version, payload, payload_hash, "
            "base_revision, source_created_at, queued_at, local_status, retry_count, next_retry_at, last_error_category, last_error_message, "
            "sync_record_id, created_at, updated_at) VALUES (:id, :idempotency_key, :message_id, :record_type, :client_record_id, "
            ":schema_version, :payload, :payload_hash, :base_revision, :source_created_at, :queued_at, :local_status, :retry_count, "
            ":next_retry_at, :last_error_category, :last_error_message, :sync_record_id, :created_at, :updated_at)",
            record,
        )
        self._conn.commit()
        return self.get(row_id)

    def _transition(self, row_id: str, new_status: str, **field_updates) -> dict:
        row = self.get(row_id)
        if row is None:
            raise KeyError(f"no outbox row with id '{row_id}'")
        allowed = SYNC_RECORD_TRANSITIONS.get(row["local_status"], ())
        if new_status not in allowed:
            raise InvalidLocalTransitionError(f"illegal local outbox transition '{row['local_status']}' -> '{new_status}'")
        updates = {**field_updates, "local_status": new_status, "updated_at": _now_iso()}
        if not all(isinstance(key, str) and key.isidentifier() for key in updates):
            raise ValueError("outbox update keys must be plain column identifiers")  # keys are interpolated into SQL below
        set_clause = ", ".join(f"{key} = :{key}" for key in updates)
        self._conn.execute(f"UPDATE outbox SET {set_clause} WHERE id = :id", {**updates, "id": row_id})  # nosec B608 - identifiers validated above, values bound
        self._conn.commit()
        return self.get(row_id)

    def mark_syncing(self, row_id: str) -> dict:
        """Called immediately before an attempt is actually sent over
        the wire -- generates a fresh `message_id` for THIS attempt
        (message_id identifies the attempt, idempotency_key
        identifies the logical operation and never changes)."""
        return self._transition(row_id, "syncing", message_id=str(uuid.uuid4()))

    def apply_ack(
        self, row_id: str, *, sync_status: str, sync_record_id: Optional[str] = None,
        error_category: Optional[str] = None, error_message: Optional[str] = None, retry_after_seconds: Optional[float] = None,
    ) -> dict:
        """Applies the CENTRAL server's verdict for this attempt. The
        local store NEVER second-guesses the server's classification --
        it mirrors whatever `sync_status` the ack carried, validated
        through the same transition table the central side itself
        enforces."""
        updates: dict = {"sync_record_id": sync_record_id, "last_error_category": error_category, "last_error_message": error_message}
        if sync_status == "retryable_failure":
            row = self.get(row_id)
            updates["retry_count"] = (row["retry_count"] if row else 0) + 1
            delay = retry_after_seconds if retry_after_seconds is not None else 5.0
            updates["next_retry_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
        return self._transition(row_id, sync_status, **updates)

    def mark_network_failure(self, row_id: str, *, message: str) -> dict:
        """The request never even reached the server (connection
        refused/timed out/DNS failure) -- classified `network`, always
        retryable, backoff computed locally since there is no server
        response to take a Retry-After from."""
        row = self.get(row_id)
        retry_count = (row["retry_count"] if row else 0) + 1
        delay = min(5.0 * (2 ** retry_count), 3600.0)
        return self._transition(
            row_id, "retryable_failure", retry_count=retry_count, last_error_category="network",
            last_error_message=message, next_retry_at=(datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(),
        )

    def mark_auth_failure(self, row_id: str, *, message: str) -> dict:
        """A 401/403 from the server -- the device's credentials are
        wrong or revoked. Never auto-retried: retrying
        with the same bad credentials can never succeed, this needs an
        operator (key rotation or re-enrollment)."""
        return self._transition(row_id, "permanent_failure", last_error_category="auth_failure", last_error_message=message)

    def cancel(self, row_id: str) -> dict:
        return self._transition(row_id, "cancelled")

    def recover_crashed(self, *, stale_after_seconds: float) -> int:
        """Crash recovery on the EDGE side -- a row left in
        `syncing` with no update for longer than `stale_after_seconds`
        means the local process died mid-send (it never even learned
        whether the server received the request). Reset to
        `retryable_failure` so the next cycle safely resends -- the
        idempotency_key guarantees the central side treats a genuine
        duplicate send as a no-op."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        rows = self._conn.execute("SELECT * FROM outbox WHERE local_status = 'syncing'").fetchall()
        recovered = 0
        for row in rows:
            updated = _parse_iso(row["updated_at"])
            if updated is not None and updated < cutoff:
                self._transition(
                    row["id"], "retryable_failure", retry_count=row["retry_count"] + 1,
                    last_error_category="network", last_error_message="local process restarted mid-send (crash recovery)",
                    next_retry_at=_now_iso(),
                )
                recovered += 1
        return recovered

    # -- reads -------------------------------------------------------

    def get(self, row_id: str) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM outbox WHERE id = ?", (row_id,)).fetchone()
        return dict(row) if row else None

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM outbox WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        return dict(row) if row else None

    def list_ready_to_send(self, *, limit: int = 100) -> list[dict]:
        """Rows due for an attempt right now: freshly `queued`, or
        `retryable_failure` whose backoff window has elapsed. Ordered
        oldest-queued-first -- never an unbounded pull (Section 11/17's
        bounded-batch discipline applies on the edge side too)."""
        now = _now_iso()
        rows = self._conn.execute(
            "SELECT * FROM outbox WHERE local_status = 'queued' "
            "OR (local_status = 'retryable_failure' AND (next_retry_at IS NULL OR next_retry_at <= ?)) "
            "ORDER BY queued_at ASC LIMIT ?",
            (now, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict:
        rows = self._conn.execute("SELECT local_status, COUNT(*) AS n FROM outbox GROUP BY local_status").fetchall()
        by_status = {row["local_status"]: row["n"] for row in rows}
        pending_statuses = ("queued", "syncing", "retryable_failure")
        pending_count = sum(by_status.get(s, 0) for s in pending_statuses)
        oldest_row = self._conn.execute(
            f"SELECT MIN(queued_at) AS oldest FROM outbox WHERE local_status IN ({','.join('?' for _ in pending_statuses)})",  # nosec B608 - only '?' placeholders are interpolated
            pending_statuses,
        ).fetchone()
        return {"by_status": by_status, "queue_depth": pending_count, "pending_sync_count": pending_count, "oldest_pending_queued_at": oldest_row["oldest"]}
