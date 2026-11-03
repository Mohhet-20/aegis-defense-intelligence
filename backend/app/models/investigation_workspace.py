"""Phase 11: investigation workspace tables.

Everything here is org-scoped. History tables (status history, integrity
checks, note revisions) are append-only: no service updates or deletes them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

MEMBER_ROLES = ("reviewer", "member")  # the owner is Investigation.assigned_user_id
LINK_RECORD_TYPES = (
    "event", "observation", "assessment", "data_source", "sensor",
    "media_asset", "evidence", "detection_result", "track",
)
INTEGRITY_RESULTS = ("match", "mismatch", "original_unavailable", "no_recorded_hash", "not_file_backed")
NOTE_KINDS = ("observed_fact", "analyst_interpretation", "hypothesis", "review_question")
NOTE_RESOLUTION_STATUSES = ("open", "resolved", "wont_address")


class InvestigationMember(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "investigation_members"
    __table_args__ = (UniqueConstraint("investigation_id", "user_id", name="uq_investigation_member"),)

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    investigation_id: Mapped[str] = mapped_column(String(36), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    added_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class InvestigationStatusHistory(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """Append-only: one row per lifecycle transition."""
    __tablename__ = "investigation_status_history"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    investigation_id: Mapped[str] = mapped_column(String(36), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    changed_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class InvestigationLink(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """A reference from an investigation to an existing record (never a copy)."""
    __tablename__ = "investigation_links"
    __table_args__ = (
        UniqueConstraint("investigation_id", "record_type", "record_id", name="uq_investigation_link"),
        Index("ix_investigation_links_record", "organization_id", "record_type", "record_id"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    investigation_id: Mapped[str] = mapped_column(String(36), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    linked_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class EvidenceIntegrityCheck(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """Append-only result of comparing stored bytes with the recorded hash.

    A `match` means the bytes currently in storage hash to the value that was
    recorded. It does not show who created the file, that it is authentic, or
    that its contents are true."""
    __tablename__ = "evidence_integrity_checks"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    algorithm: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    recorded_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    computed_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    checked_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class InvestigationNote(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "investigation_notes"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    investigation_id: Mapped[str] = mapped_column(String(36), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("evidence_items.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_note_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("investigation_notes.id", ondelete="CASCADE"), nullable=True, index=True)
    note_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="analyst_interpretation", index=True)
    body: Mapped[str] = mapped_column(String(8000), nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    author_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assignee_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolution_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    resolved_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    # Optimistic concurrency token; incremented on every edit.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class InvestigationNoteRevision(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """Append-only: the full content of every version of a note."""
    __tablename__ = "investigation_note_revisions"
    __table_args__ = (UniqueConstraint("note_id", "version", name="uq_note_revision_version"),)

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    note_id: Mapped[str] = mapped_column(String(36), ForeignKey("investigation_notes.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    note_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    body: Mapped[str] = mapped_column(String(8000), nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    changed_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    change_summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
