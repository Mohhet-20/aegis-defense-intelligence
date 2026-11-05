"""The durable, idempotent CENTRAL inbox for edge synchronization.
One row per logical record a device has ever
attempted to sync -- this table IS the authoritative state machine
Section 6 requires, and IS the queryable "what's pending/failed/
conflicted" view the Edge Operations Center reads from. See
docs/architecture/SYNC_PROTOCOL.md and docs/architecture/EDGE_ARCHITECTURE.md.

Deliberate scope boundary, stated here and in
docs/architecture/EDGE_ARCHITECTURE.md Section 7: an accepted
SyncRecord is NOT automatically materialized into a canonical `Event`/
`Observation`/`Evidence` row. It is itself the durable, auditable,
queryable record of what the edge device sent and the central system
durably accepted -- promoting it into a first-class domain row is a
reasonable, explicitly deferred follow-up, not a silent gap.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

# Section 6's required state set, verbatim.
SYNC_RECORD_STATUSES = (
    "queued", "syncing", "synced", "retryable_failure",
    "permanent_failure", "conflict", "quarantined", "cancelled",
)

# Legal transitions -- enforced by edge_sync_service, never bypassed by
# a route or a direct ORM write elsewhere. A transition not listed here
# is rejected with a ValueError ("prevent invalid state
# changes").
SYNC_RECORD_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "queued": ("syncing", "cancelled"),
    "syncing": ("synced", "retryable_failure", "permanent_failure", "conflict", "quarantined", "queued"),
    "retryable_failure": ("syncing", "permanent_failure", "cancelled"),
    "synced": (),
    # "permanent_failure" is terminal for AUTOMATIC processing -- nothing
    # in edge_sync_service ever auto-transitions out of it. The one
    # explicit exception is an operator-initiated force-retry
    # (edge_sync_service.force_retry_sync_record, gated on
    # EDGE_SYNC_MANAGE), which is a deliberate human override, not
    # another automatic attempt -- it resets retry_count and re-enters
    # "syncing" directly.
    "permanent_failure": ("syncing",),
    "conflict": ("synced", "permanent_failure"),  # only via explicit conflict resolution
    "quarantined": ("permanent_failure",),  # only via explicit operator action, never auto-retried
    "cancelled": (),
}

# Record types this layer's protocol actually accepts. "annotation" is
# the one MUTABLE, revisioned type -- every other
# type is treated as append-only/immutable.
SYNC_RECORD_TYPES = ("observation_capture", "event_capture", "annotation", "inference_output")
MUTABLE_SYNC_RECORD_TYPES = ("annotation",)

ERROR_CATEGORIES = (
    "network", "server_error", "rate_limited", "auth_failure",
    "validation_error", "integrity_failure", "conflict",
)


class SyncRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "sync_records"
    __table_args__ = (
        # THE idempotency guarantee ("a stable idempotency
        # key for each logical operation"). Re-submitting the same
        # (device, idempotency_key) is a no-op, never a duplicate row.
        UniqueConstraint("organization_id", "device_id", "idempotency_key", name="uq_sync_records_device_idempotency"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)

    message_id: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    batch_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    protocol_version: Mapped[str] = mapped_column(String(20), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)

    record_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    client_record_id: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    # Only meaningful for MUTABLE_SYNC_RECORD_TYPES -- the revision this
    # payload claims to be, and the revision it was based on (for
    # optimistic-concurrency conflict detection, Section 8.2/8.3).
    base_revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # The four distinct timestamps Section 9 requires kept separate.
    source_created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    queued_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    # received_at is `created_at` (TimestampMixin) -- when THIS row was
    # first written, i.e. when the central system first received this
    # attempt. processed_at is when it left "syncing" for a terminal or
    # conflict/quarantine state.
    processed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    sync_status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True, index=True)
    last_error_category: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # Bounded, never the raw payload -- Section 15 ("do not log entire
    # sensitive payloads by default").
    last_error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Set only when this record superseded an earlier revision of the
    # same mutable client_record_id (Section 8.2/8.3's append-a-new-
    # revision-rather-than-overwrite discipline).
    supersedes_sync_record_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("sync_records.id", ondelete="SET NULL"), nullable=True)

    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
