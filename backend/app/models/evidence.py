"""Evidence (Section 3B). A generic, auditable reference to a
piece of supporting material an analyst or the fusion pipeline wants to
cite: an existing Event (observation), a RawRecord, a sensor
Observation, or an analyst-authored note/report/document reference.

This is deliberately a REFERENCE layer, not a media-storage layer --
Section 3B explicitly says "do not store duplicate copies of large
media files unnecessarily" and the repository has no file-storage
subsystem yet. `external_reference_uri` records where a document/image/
video actually lives; this table never fetches, stores, or renders that
content. `content` is for genuinely small analyst-authored text (a
note, a short report) that has nowhere else to live.

Every row must point at something real: at least one of
event_id/raw_record_id/observation_id/content/external_reference_uri
must be set (enforced both in `evidence_service.py` and by the CHECK
constraint below) -- Evidence is never allowed to exist as a bare,
contentless placeholder.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

EVIDENCE_TYPES = (
    "observation",       # a canonical Event
    "ingestion_record",  # a RawRecord
    "sensor_observation",  # a Sensor Observation row
    "report",             # analyst-authored report text
    "analyst_note",       # a short analyst note
    "document",           # a reference to an external document
    "media_reference",    # a reference to an external image/video
    # References to platform records (aegis://<type>/<id> URI)
    "media_asset",
    "detection",
    "track",
    "data_source",
    "assessment_version",
)
EVIDENCE_ACCESS_CLASSIFICATIONS = ("unclassified", "internal", "restricted")
EVIDENCE_REVIEW_STATUSES = ("unreviewed", "in_review", "reviewed", "disputed")


class Evidence(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "evidence_items"
    __table_args__ = (
        CheckConstraint(
            "event_id IS NOT NULL OR raw_record_id IS NOT NULL OR observation_id IS NOT NULL "
            "OR content IS NOT NULL OR external_reference_uri IS NOT NULL",
            name="ck_evidence_items_has_a_real_reference",
        ),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    evidence_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    # Exactly the reference this evidence item actually carries -- never
    # more than one of these three FK-backed references is expected to
    # be set per row, but nothing enforces "exactly one" at the DB level
    # because a report/note legitimately carries zero of them (it has
    # `content` instead). See evidence_service.py for the create-time
    # validation that ties evidence_type to which fields are required.
    event_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True)
    raw_record_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("raw_records.id", ondelete="SET NULL"), nullable=True, index=True)
    observation_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("observations.id", ondelete="SET NULL"), nullable=True, index=True)

    # Free text for a report/analyst_note -- never populated for an
    # evidence_type backed by a real FK reference above.
    content: Mapped[Optional[str]] = mapped_column(String(8000), nullable=True)

    # A document/media_reference's location. Metadata only -- this
    # platform never fetches or renders whatever this URI points to.
    external_reference_uri: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    # Optional integrity hash an analyst or an upstream system can record
    # for the referenced content -- never computed by fetching the URI.
    integrity_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # when a `media_reference` Evidence row was
    # created by promoting a specific, analyst-confirmed DetectionResult
    # (see app/services/detection_review_service.py), this points at
    # that exact detection -- the last link in the required lineage
    # "Media asset -> Inference job -> Model/version -> Detection result
    # -> Derived evidence reference -> Analyst review." NULL for every
    # other evidence_type and for a media_reference created by hand
    # (an analyst citing a video that was never run through this
    # platform's own CV pipeline). Nothing here changes the existing
    # CHECK constraint or _REQUIRES_URI validation -- a media_reference
    # row still always needs external_reference_uri; this is strictly
    # additional lineage, never a substitute reference.
    detection_result_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("detection_results.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Additions. All nullable/defaulted; unknown stays NULL.
    access_classification: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unreviewed", index=True)
    captured_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    processing_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    media_asset_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    integrity_hash_algorithm: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    hash_recorded_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    supersedes_evidence_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("evidence_items.id", ondelete="SET NULL"), nullable=True)
    superseded_by_evidence_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("evidence_items.id", ondelete="SET NULL"), nullable=True)
