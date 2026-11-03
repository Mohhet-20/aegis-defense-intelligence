from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

RISK_HUMAN_REVIEW_STATUSES = ("pending", "confirmed", "overridden", "dismissed")

# Section 15 / docs/architecture/AI_ANALYTICS_CONTRACTS.md principle 8:
# a score is a number on THIS documented scale, never implicitly a
# calibrated probability.
RISK_SCORE_SCALE = "0-100 (uncalibrated; see docs/architecture/AI_ANALYTICS_CONTRACTS.md)"


class RiskAssessment(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """Storage + review-workflow shape only in Phase 1. Seed data
    creates rows with method="seed_example_v0" -- there is no real
    scoring model yet. See docs/architecture/AI_ANALYTICS_CONTRACTS.md."""

    __tablename__ = "risk_assessments"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    subject_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    assessed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    # Names the method/model that produced this score -- NEVER a bare
    # score with no attribution (AI_ANALYTICS_CONTRACTS.md principle 1).
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    model_record_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("model_records.id", ondelete="SET NULL"), nullable=True)

    score: Mapped[float] = mapped_column(Float, nullable=False)
    score_scale: Mapped[str] = mapped_column(String(200), nullable=False, default=RISK_SCORE_SCALE)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    contributing_factors: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)

    human_review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    reviewer_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    reviewer_notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    data_origin: Mapped[str] = mapped_column(String(30), nullable=False, default="synthetic_demo")
