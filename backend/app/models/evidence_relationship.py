"""EvidenceRelationship (Phase 3, Section 3D). A generic, explainable
link between two referenceable records -- an Event (observation) or an
Evidence item -- on EITHER side. This is deliberately a different,
broader concept from Phase 2's `EventCorrelation`:

  * `EventCorrelation` (unchanged, still the system of record for it)
    is ONLY ever event<->event, ONLY ever rule-based
    (`correlation_service.recompute()`), and its review workflow is
    only confirm/reject.
  * `EvidenceRelationship` can link an event to an event, an event to
    an evidence item, or an evidence item to an evidence item; its
    `origin` can be `rule_based`, `model_assisted`, OR
    `analyst_created` (an analyst can draw a link from scratch, which
    `EventCorrelation` has no way to represent); and its review
    workflow additionally supports `uncertain` and an explicit
    `reverse` action that un-confirms a prior decision without ever
    deleting the row.

A relationship is never proof that two records describe the same
real-world object or event -- see
docs/data/EVIDENCE_RELATIONSHIP_MODEL.md.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

RELATIONSHIP_TYPES = (
    "supports",
    "contradicts",
    "corroborates",
    "derived_from",
    "duplicate_candidate",
    "temporally_associated",
    "spatially_associated",
    "shares_source_identifier",
    "analyst_linked",
    # Phase 6, Section 11: a bounded-time-window comparison between two
    # sensor observations (wrapped as "sensor_observation" Evidence --
    # never a direct event<->event link). Never implies the two
    # observations describe the same real-world event; see
    # docs/analytics/CROSS_SOURCE_COMPARISON.md.
    "cross_source_comparison",
)

# "rule_based": produced by fusion_service's candidate generation.
# "model_assisted": reserved for a future scored/ML-assisted generator
#   -- nothing in this phase produces this value yet (see
#   CONFIDENCE_AND_SOURCE_RELIABILITY.md's "what this does NOT do").
# "analyst_created": a human drew this link from nothing: the one kind
#   of relationship EventCorrelation can never represent.
RELATIONSHIP_ORIGINS = ("rule_based", "model_assisted", "analyst_created")

RELATIONSHIP_REVIEW_STATUSES = ("candidate", "confirmed", "rejected", "uncertain")

REFERENCEABLE_TYPES = ("event", "evidence")


class EvidenceRelationship(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "evidence_relationships"
    __table_args__ = (
        CheckConstraint(
            "(source_event_id IS NOT NULL) != (source_evidence_id IS NOT NULL)",
            name="ck_evidence_relationships_one_source_ref",
        ),
        CheckConstraint(
            "(target_event_id IS NOT NULL) != (target_evidence_id IS NOT NULL)",
            name="ck_evidence_relationships_one_target_ref",
        ),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    # Exactly one of each pair is set -- enforced by the CHECK
    # constraints above AND by relationship_service.py before insert.
    source_event_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=True, index=True)
    source_evidence_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=True, index=True)
    target_event_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=True, index=True)
    target_evidence_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=True, index=True)

    relationship_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Always a human-readable explanation of WHY this relationship
    # exists -- "shared_source_id + temporal_proximity" for a rule-based
    # link, or the analyst's own stated reason for an analyst_created one.
    explanation: Mapped[str] = mapped_column(String(2000), nullable=False)
    supporting_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate", index=True)
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    # A reversal never deletes history -- it flips review_status back
    # toward "candidate" and records that this happened, on top of the
    # append-only AuditRecord trail every review action also writes.
    is_reversed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_reversed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    # NULL for a rule_based/model_assisted relationship -- only an
    # analyst_created one has a human author.
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Which fusion job produced this row, if it was rule-based -- NULL
    # for an analyst_created relationship. Deliberately a plain string,
    # not a FK, so this table never depends on fusion_jobs existing for
    # an analyst-created row to be valid.
    fusion_batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
