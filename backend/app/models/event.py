from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime
from app.models.mixins import GeoLocationMixin

EVENT_CLASSIFICATIONS = ("unclassified", "internal", "restricted")
EVENT_PROCESSING_STATUSES = ("ingested", "normalized", "correlated", "archived")

# What produced this row -- Rule 9: never let a synthetic or user-
# uploaded record pass as a live connected feed. "external_source"
# is a record fetched from a real, registered, authorized
# connector (e.g. http_api) -- distinct from a manual upload and
# always traceable via RawRecord/provenance to the source that
# produced it.
EVENT_DATA_ORIGINS = ("synthetic_demo", "user_upload", "external_source")


class Event(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, GeoLocationMixin):
    """The canonical event record. Created ONLY by the ingestion
    pipeline (app/services/ingestion_service.py) or the seed script --
    there is no raw "create event" API, because every event must carry
    real provenance (Rule 9) and a real source_id, which only the
    ingestion path guarantees."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_events_source_external_id"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    # Dedup key from the source's own record identifier -- NULL means
    # "this source never supplies a stable external id," in which case
    # duplicate detection falls back to a content hash (see
    # ingestion_service.py); it is never defaulted to a made-up value.
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)

    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)

    asset_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)

    # Severity, priority and confidence are three DIFFERENT numbers
    # (Section 7's explicit distinction) -- never collapsed into one
    # field. source_severity is whatever the source itself reported (a
    # free string -- sources use wildly different scales); priority is
    # this platform's own analytical triage; confidence is only set
    # when there is a real basis to estimate it.
    source_severity: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    priority: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    classification: Mapped[str] = mapped_column(String(20), nullable=False, default="unclassified")
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    processing_status: Mapped[str] = mapped_column(String(20), nullable=False, default="ingested", index=True)

    # Rule 9 enforcement point: every event states where it actually
    # came from. "synthetic_demo" for seed data, "user_upload" for a
    # real JSON/CSV import through the ingestion pipeline. Nothing else
    # is a valid value until a real connector (Phase 2+) exists.
    data_origin: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    ingestion_job_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("ingestion_jobs.id", ondelete="SET NULL"), nullable=True)
