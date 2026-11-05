"""Conflict review queue. List/inspect/resolve
for `SyncConflict` rows -- deliberately separate from the
`conflict_service.py` (see app/models/sync_conflict.py's module
docstring). Every resolution here is an explicit, audited human
decision; nothing here is ever resolved merely because a record arrived
later (Section 8, binding: no unconditional last-write-wins), and this
module never lets the submitting edge device's own claim override
central authorization or tenant ownership -- resolution is always an
org-scoped human action through this service, never something a device
can trigger over the sync protocol.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sync_conflict import SYNC_CONFLICT_RESOLUTION_STRATEGIES, SyncConflict
from app.models.sync_record import SyncRecord
from app.services import audit_service


class InvalidConflictResolutionError(ValueError):
    pass


class ConflictAlreadyResolvedError(ValueError):
    pass


def get_conflict(db: Session, organization_id: str, conflict_id: str) -> Optional[SyncConflict]:
    stmt = select(SyncConflict).where(SyncConflict.id == conflict_id, SyncConflict.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_conflicts_query(
    organization_id: str, *, resolution_status: Optional[str] = None, device_id: Optional[str] = None, record_type: Optional[str] = None,
):
    stmt = select(SyncConflict).where(SyncConflict.organization_id == organization_id)
    if resolution_status:
        stmt = stmt.where(SyncConflict.resolution_status == resolution_status)
    if device_id:
        stmt = stmt.where(SyncConflict.device_id == device_id)
    if record_type:
        stmt = stmt.where(SyncConflict.record_type == record_type)
    return stmt.order_by(SyncConflict.created_at.desc())


def resolve_conflict(
    db: Session, conflict: SyncConflict, *, resolution_strategy: str, actor_user_id: str, resolution_note: Optional[str] = None,
) -> SyncConflict:
    """Section 8.4: list/inspect/resolve, with a full audit trail.
    `keep_central`: the device's submitted revision is discarded, the
    conflicting SyncRecord moves to `permanent_failure` (it will never
    become the authoritative version). `keep_local`: the device's
    submission becomes authoritative -- the conflicting SyncRecord is
    promoted to `synced` with the next revision number, superseding
    whatever was central at conflict time. `merged`: an authorized
    reviewer composed a merged outcome externally (this project has no
    generic field-level merge UI); recorded via `resolution_note`, and
    the conflicting SyncRecord still moves to `permanent_failure` since
    its own submitted payload was NOT taken verbatim -- the merged
    content, if it needs to become the new central record, is entered
    through the normal device/analyst submission path, not fabricated
    here from a free-text note."""
    if conflict.resolution_status == "resolved":
        raise ConflictAlreadyResolvedError(f"conflict {conflict.id} was already resolved")
    if resolution_strategy not in SYNC_CONFLICT_RESOLUTION_STRATEGIES:
        raise InvalidConflictResolutionError(f"'{resolution_strategy}' is not a valid resolution_strategy (must be one of {SYNC_CONFLICT_RESOLUTION_STRATEGIES})")

    sync_record = db.execute(
        select(SyncRecord).where(SyncRecord.id == conflict.sync_record_id, SyncRecord.organization_id == conflict.organization_id)
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if sync_record is not None and sync_record.sync_status == "conflict":
        if resolution_strategy == "keep_local":
            central_revision = conflict.central_version.get("revision") or 0
            sync_record.revision = central_revision + 1
            sync_record.sync_status = "synced"
            sync_record.last_error_category = None
            sync_record.last_error_message = f"conflict resolved by {actor_user_id}: keep_local"
        else:  # keep_central or merged -- the device's own submission never becomes authoritative verbatim
            sync_record.sync_status = "permanent_failure"
            sync_record.last_error_category = "conflict"
            sync_record.last_error_message = f"conflict resolved by {actor_user_id}: {resolution_strategy}"
        sync_record.processed_at = now
        db.add(sync_record)

    conflict.resolution_status = "resolved"
    conflict.resolution_strategy = resolution_strategy
    conflict.resolved_by_user_id = actor_user_id
    conflict.resolved_at = now
    conflict.resolution_note = resolution_note
    db.add(conflict)
    db.commit()
    db.refresh(conflict)

    audit_service.record(
        db, action="edge_conflict.resolve", actor_user_id=actor_user_id, organization_id=conflict.organization_id,
        target_type="sync_conflict", target_id=conflict.id,
        context_metadata={"resolution_strategy": resolution_strategy, "sync_record_id": conflict.sync_record_id, "resolution_note": resolution_note},
    )
    db.commit()
    return conflict
