"""AssessmentScoreSnapshot. An immutable,
append-only record of one advisory review-priority computation for one
assessment VERSION. Re-scoring never overwrites: it appends a new row, so
the history of what the rule said at each point stays reconstructable.

The score is an advisory ranking of review attention (see
app/analytics/scoring.py) and is kept distinct from model confidence,
evidence quality, source reliability and uncertainty, which are stored
in their own columns rather than folded into `score`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime


class AssessmentScoreSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "assessment_score_snapshots"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_version: Mapped[int] = mapped_column(Integer, nullable=False)

    rule_key: Mapped[str] = mapped_column(String(60), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_config: Mapped[dict] = mapped_column(JSON, default=dict)

    score: Mapped[float] = mapped_column(Float, nullable=False)
    score_scale: Mapped[str] = mapped_column(String(300), nullable=False)
    priority_band: Mapped[str] = mapped_column(String(10), nullable=False)

    factors: Mapped[list] = mapped_column(JSON, default=list)
    # Distinct concepts, never blended into `score`:
    distinct_concepts: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_considered: Mapped[list] = mapped_column(JSON, default=list)
    data_quality_limitations: Mapped[list] = mapped_column(JSON, default=list)
    conflicts: Mapped[list] = mapped_column(JSON, default=list)
    missing_information: Mapped[list] = mapped_column(JSON, default=list)

    computed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    computed_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
