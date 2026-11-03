"""Phase 12: retrieval index + copilot conversations.

The index is a DERIVED, refreshable copy of text from authoritative records;
it is never the source of truth and access is always re-checked against the
live record at query time. Conversations are per-user and hard-deleted on
request; a message is never evidence (see CopilotMessage)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

INDEXABLE_RECORD_TYPES = (
    "investigation", "investigation_note", "event", "observation", "assessment",
    "assessment_review", "evidence", "data_source", "media_asset", "scenario",
)
# Types whose content is HYPOTHETICAL. They are indexed with explicit type
# metadata but are excluded from searches/copilot answers unless the caller
# names the type in `record_types`.
SIMULATED_RECORD_TYPES = ("scenario",)
DOCUMENT_STATUSES = ("indexed", "empty", "unsupported", "error", "invalidated")
RETENTION_STATES = ("active", "invalidated")
CHUNK_PRIMARY = "chunk"


class RetrievalDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """One row per (organization, record). `version` increases when the
    indexed text of the record changes."""
    __tablename__ = "retrieval_documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "record_type", "record_id", name="uq_retrieval_document_record"),
        Index("ix_retrieval_documents_scope", "organization_id", "status", "record_type"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    investigation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    source_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    review_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    source_time: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    source_updated_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    extraction_method: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="indexed", index=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    retention_state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    invalidated_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    invalidation_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


class RetrievalChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "retrieval_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "position", name="uq_retrieval_chunk_position"),
        Index("ix_retrieval_chunks_scope", "organization_id", "record_type", "record_id"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("retrieval_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    text: Mapped[str] = mapped_column(String(4000), nullable=False)
    text_lower: Mapped[str] = mapped_column(String(4000), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    source_time: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class RetrievalIndexRun(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """Operational visibility for an indexing run."""
    __tablename__ = "retrieval_index_runs"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    triggered_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    errors: Mapped[list] = mapped_column(JSON, default=list)


class CopilotConversation(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "copilot_conversations"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    investigation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


class CopilotMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """role 'user': the question text. role 'assistant': `answer` holds the
    structured response. Neither is a source of facts: retrieval never
    indexes conversations, and prior answers are not fed back as evidence."""
    __tablename__ = "copilot_messages"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("copilot_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)
    task: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    answer: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    answer_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
