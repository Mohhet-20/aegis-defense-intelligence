"""Reusable tenant-isolation helpers (Phase 14, Phase B/C).

Convention (unchanged from earlier phases): a record that belongs to another
organization is indistinguishable from one that does not exist -- both give
the same 404. These helpers apply that convention to *referenced* records
(ids supplied in a request body), which per-resource GET routes alone do not
cover.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Type

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session


def require_in_org(db: Session, model: Type[Any], organization_id: str, record_id: Optional[str], label: str, *, optional: bool = True):
    """Returns the row if `record_id` belongs to `organization_id`, None if
    `record_id` is None and `optional`, else raises 404 '<label> not found'."""
    if record_id is None:
        if optional:
            return None
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found")
    row = db.scalar(select(model).where(model.id == record_id, model.organization_id == organization_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found")
    return row


def require_all_in_org(db: Session, model: Type[Any], organization_id: str, record_ids: Iterable[str], label: str) -> None:
    ids = set(record_ids)
    if not ids:
        return
    found = set(db.scalars(select(model.id).where(model.id.in_(ids), model.organization_id == organization_id)).all())
    if found != ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found")


def reject_foreign_ids(db: Session, model: Type[Any], organization_id: str, record_ids: Iterable[str], label: str) -> None:
    """Legacy-tolerant variant for free-form id lists (e.g. an investigation's
    historical `linked_event_ids` JSON, which may legitimately contain ids that
    no longer exist): ids that do not exist anywhere are tolerated, but an id
    that exists in ANOTHER organization is rejected."""
    ids = set(record_ids)
    if not ids:
        return
    foreign = db.scalar(select(model.id).where(model.id.in_(ids), model.organization_id != organization_id).limit(1))
    if foreign is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found")
