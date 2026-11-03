"""AssessmentReview. An append-only log of human
review decisions on an assessment. A later decision never edits an
earlier row; it appends a new one whose `supersedes_review_id` points at
the previous latest decision, so the full decision history and the
reasons for each change are preserved.

Accepting an assessment here does NOT change `Assessment.status` or
trigger anything else: review decisions are records of human judgement,
not workflow side effects.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

REVIEW_DECISIONS = ("accepted", "rejected", "further_review_requested")
INFORMATION_FLAGS = ("insufficient_information", "conflicting_information")


class AssessmentReview(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "assessment_reviews"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    score_snapshot_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("assessment_score_snapshots.id", ondelete="SET NULL"), nullable=True)

    decision: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    notes: Mapped[str] = mapped_column(String(2000), nullable=False)
    # Required when this decision changes a previous one.
    change_reason: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    information_flags: Mapped[list] = mapped_column(JSON, default=list)

    # What the advisory score said at the moment of the decision, kept so
    # model-versus-human difference stays visible later.
    advisory_score_at_review: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    advisory_band_at_review: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    reviewer_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    supersedes_review_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("assessment_reviews.id", ondelete="SET NULL"), nullable=True)
