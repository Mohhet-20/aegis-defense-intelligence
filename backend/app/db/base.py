"""Shared declarative base + reusable mixins."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import UTCDateTime


class Base(DeclarativeBase):
    pass


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPrimaryKeyMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class OrgScopedMixin:
    """Marker mixin documenting that a model's rows belong to one
    organization. See docs/architecture/ARCHITECTURE_DECISIONS.md
    "Tenant isolation: modeled, not yet enforced" -- the organization_id
    column exists on each concrete model, but no query filters by it
    yet. That enforcement is the job."""
