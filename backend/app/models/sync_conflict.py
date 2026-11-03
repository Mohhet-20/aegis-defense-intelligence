"""Sync-time conflict records. Deliberately a
SEPARATE model from Phase 3's `Conflict`
(app/models/conflict.py)/`conflict_service.py` -- that model detects a
contradiction between two already-correlated `Event` rows (an
event-fusion concern). This model detects a contradiction between an
edge device's submitted revision of a MUTABLE record and the central
system's current revision of that same logical record (a
synchronization-protocol concern). The two never share a table, a
service, or a review queue -- see
docs/architecture/EDGE_ARCHITECTURE.md Section 2's reuse table.

Never resolved by unconditional last-write-wins (Section 8, binding):
every resolution here is an explicit, authorized, audited human
decision recorded in `resolution_strategy`/`resolved_by_user_id`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

SYNC_CONFLICT_REASONS = ("revision_mismatch",)
SYNC_CONFLICT_RESOLUTION_STATUSES = ("unresolved", "resolved")
# "keep_central": the device's submitted revision is discarded, central
# stays authoritative. "keep_local": the device's submitted revision
# becomes the new current revision. "merged": an authorized reviewer
# wrote a new, explicitly merged revision (recorded in
# `resolution_note`, since this project has no generic field-level
# merge UI -- a human composes the merged content externally and the
# resolution records that decision, never performs it automatically).
SYNC_CONFLICT_RESOLUTION_STRATEGIES = ("keep_central", "keep_local", "merged")


class SyncConflict(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "sync_conflicts"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    sync_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("sync_records.id", ondelete="CASCADE"), nullable=False, index=True)

    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    client_record_id: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    conflict_reason: Mapped[str] = mapped_column(String(30), nullable=False)

    # Full snapshots, not just a diff -- Section 8.4: "retrieve both
    # versions and their metadata." Both preserved exactly as they
    # were at conflict-detection time.
    local_version: Mapped[dict] = mapped_column(JSON, nullable=False)
    central_version: Mapped[dict] = mapped_column(JSON, nullable=False)

    resolution_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unresolved", index=True)
    resolution_strategy: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    resolved_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
