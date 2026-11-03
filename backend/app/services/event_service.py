from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.event import Event


def get_event(db: Session, organization_id: str, event_id: str) -> Optional[Event]:
    stmt = select(Event).where(Event.id == event_id, Event.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_events_query(
    organization_id: str,
    *,
    event_type: Optional[str] = None,
    source_id: Optional[str] = None,
    priority: Optional[str] = None,
    data_origin: Optional[str] = None,
):
    """Deterministic sort (newest observed_at first, then id as a
    tiebreaker so pagination is stable across requests) -- Section 8
    requires deterministic sorting, not just "sorted by whatever the
    database feels like returning."""
    stmt = select(Event).where(Event.organization_id == organization_id)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    if source_id:
        stmt = stmt.where(Event.source_id == source_id)
    if priority:
        stmt = stmt.where(Event.priority == priority)
    if data_origin:
        stmt = stmt.where(Event.data_origin == data_origin)
    return stmt.order_by(Event.observed_at.desc(), Event.id)
