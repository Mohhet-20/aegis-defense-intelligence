"""Intelligence assessment. A bounded, versioned,
explainable analytical write-up that must be traceable to the evidence
it relies on via `AssessmentEvidenceLink` rows. This is a storage and
review-workflow shape, same spirit as the `RiskAssessment` --
nothing here runs a model or fabricates a conclusion; it organizes
evidence and uncertainty for human analysts.

`confidence_level` is a documented QUALITATIVE category
(low/moderate/high), never a fabricated probability -- see
docs/analytics/CONFIDENCE_AND_SOURCE_RELIABILITY.md. An assessment
object is never allowed to declare something hostile based solely on a
heuristic score; that judgment, and its caveats, belongs in
`confidence_rationale` as the analyst's own words.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

ASSESSMENT_STATUSES = ("draft", "in_review", "published", "archived")
# draft -> in_review -> published -> archived is the only forward path;
# published -> archived directly is also allowed (see
# assessment_service.ALLOWED_STATUS_TRANSITIONS). Nothing can move
# backward to "draft" once it has left it -- a correction becomes a new
# version (see AssessmentRevision below), never a reopened draft.
CONFIDENCE_LEVELS = ("low", "moderate", "high")
ASSESSMENT_EVIDENCE_ROLES = ("supporting", "contradicting")


class Assessment(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "assessments"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    question: Mapped[str] = mapped_column(String(1000), nullable=False)
    scope_description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    scope_start: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    scope_end: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    summary: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)
    # Free-text lists -- an analyst's own stated assumptions/gaps, never
    # auto-generated or inferred by this platform.
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    information_gaps: Mapped[list] = mapped_column(JSON, default=list)

    confidence_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    confidence_rationale: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)

    author_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Set only when a later Assessment explicitly supersedes this one --
    # never set automatically; always a deliberate analyst action
    # (assessment_service.supersede()).
    superseded_by_assessment_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("assessments.id", ondelete="SET NULL"), nullable=True)


class AssessmentEvidenceLink(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "assessment_evidence_links"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)

    # Exactly one of these two is set -- validated in assessment_service.py.
    event_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=True, index=True)
    evidence_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=True, index=True)

    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)


class AssessmentRevision(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """An immutable snapshot taken BEFORE each update that changes a
    meaningful field -- no update route exists for this table; the only
    way a row is created is assessment_service.update_assessment()
    writing one on its way to applying the new state. This is what
    "version history" actually means here: not a diff engine, a
    plain append-only snapshot log, same spirit as AuditRecord."""

    __tablename__ = "assessment_revisions"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)

    version: Mapped[int] = mapped_column(nullable=False, index=True)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    change_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
