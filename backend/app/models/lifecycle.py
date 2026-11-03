"""Data-lifecycle requests (Phase 14, Phase G).

One row per requested archive/delete of a lifecycle-managed record. The row
is the approval workflow state AND the durable outcome record; it never
holds the deleted content itself, only identifiers, counts and the dry-run
impact snapshot taken at request time.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

LIFECYCLE_ACTIONS = ("archive", "delete")
LIFECYCLE_STATUSES = ("pending", "approved", "rejected", "executed", "cleanup_pending", "failed", "cancelled")


class LifecycleRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "lifecycle_requests"
    __table_args__ = (
        CheckConstraint("action in ('archive','delete')", name="ck_lifecycle_action"),
        CheckConstraint(
            "status in ('pending','approved','rejected','executed','cleanup_pending','failed','cancelled')",
            name="ck_lifecycle_status",
        ),
        Index("ix_lifecycle_requests_org_status", "organization_id", "status", "created_at"),
        Index("ix_lifecycle_requests_target", "organization_id", "resource_type", "resource_id"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    executed_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    impact: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
