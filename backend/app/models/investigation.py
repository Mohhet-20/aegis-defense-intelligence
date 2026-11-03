from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

INVESTIGATION_STATUSES = ("draft", "open", "active", "pending_review", "closed", "archived")
# Phase 11: explicit lifecycle. `pending_review` is this codebase's
# "under_review". open->closed stays legal (Phase 3 behaviour); archived is
# terminal and only reachable from closed.
INVESTIGATION_TRANSITIONS = {
    "draft": ("open",),
    "open": ("active", "pending_review", "closed"),
    "active": ("open", "pending_review", "closed"),
    "pending_review": ("active", "closed"),
    "closed": ("open", "archived"),
    "archived": (),
}
INVESTIGATION_PRIORITIES = ("low", "normal", "high", "urgent")
INVESTIGATION_REVIEW_STATUSES = ("not_reviewed", "in_review", "reviewed")


class Investigation(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "investigations"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal", index=True)

    assigned_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Linked events / evidence references as JSON id lists rather than
    # a join table -- Phase 11 (Investigations and Evidence Management)
    # is where a full evidence/case workflow belongs. Phase 3 adds the
    # real `Evidence` table (app/models/evidence.py); `evidence_refs`
    # here can now hold real `Evidence.id` values (previously these were
    # a placeholder list with no backing entity -- Phase 1 said so
    # explicitly), though nothing in this phase renames or migrates the
    # column, and it still accepts a free-form string for anything that
    # predates Evidence existing.
    linked_event_ids: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)

    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_reviewed")
    resolution_notes: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)

    # Phase 3, Section 3C: "purpose and scope" and "owner and
    # authorized collaborators" -- assigned_user_id above is the owner;
    # collaborator_user_ids is the explicit, auditable allow-list of
    # who else may act on this case (see investigation_service.py's
    # authorization helper). Both new columns are nullable/empty-default
    # so every Phase-1/2 investigation row remains valid unchanged.
    purpose: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    collaborator_user_ids: Mapped[list] = mapped_column(JSON, default=list)

    # Phase 11 additions (all nullable/defaulted so earlier rows stay valid).
    tags: Mapped[list] = mapped_column(JSON, default=list)
    closure_reason: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # When true, only the owner (assigned_user_id), explicit members and
    # administrators can see or change the investigation.
    is_restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
