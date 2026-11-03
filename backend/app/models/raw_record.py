"""Raw-record provenance. Preserves the record
exactly as a connector produced it -- before normalization -- alongside
the metadata needed to answer "where did this come from, when, through
what code, and what did validation say about it," independent of
whether the record ever became an Event.

Every accepted, rejected, quarantined, AND duplicate record gets a
RawRecord row (not just the ones that become Events) -- that's the
whole point: an analyst can inspect what a source actually sent, even
for a record this platform decided not to use as evidence.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

# Mirrors ValidationOutcome.status (app.services.validation_service) --
# kept as a plain string column rather than importing that module, so
# a schema/service refactor there never forces a migration here.
RAW_RECORD_VALIDATION_STATUSES = ("valid", "invalid")


class RawRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "raw_records"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    ingestion_job_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("ingestion_jobs.id", ondelete="SET NULL"), nullable=True, index=True)

    # Set only once this raw record was successfully normalized AND
    # accepted as a new (non-duplicate) Event. NULL for a rejected,
    # quarantined, or duplicate record -- there is no event to link to.
    event_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True)

    external_record_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    connector_type: Mapped[str] = mapped_column(String(50), nullable=False)
    connector_version: Mapped[str] = mapped_column(String(20), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(20), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # sha256-derived fingerprint of the raw payload (see
    # normalization_service.content_fingerprint) -- the fallback dedup
    # key, and also useful to an analyst spotting exact-repeat uploads.
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # The record exactly as the connector produced it. Access to this
    # column is gated the same way raw event payload access is -- see
    # app.core.security's data-quality/provenance permission check in
    # the raw-record API routes -- because it may carry sensitive
    # source-side detail that normalized fields intentionally drop.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_observed_at_raw: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    validation_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    validation_warnings: Mapped[list] = mapped_column(JSON, default=list)

    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    duplicate_of_raw_record_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("raw_records.id", ondelete="SET NULL"), nullable=True)
    duplicate_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
