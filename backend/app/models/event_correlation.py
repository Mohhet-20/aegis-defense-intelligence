"""Event correlation. A PAIRWISE, transparent,
rule-based relationship between two existing events -- never a merge.
Both original events always remain independently inspectable; this
table only records "here is why the correlation engine flagged these
two as possibly related," for an analyst to review and confirm or
reject -- it is explicitly NOT an assertion of fact ("a
grouping for analyst review, not a certainty claim").
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

# "candidate": produced by a rule run, not yet looked at.
# "confirmed" / "rejected": an analyst's own review decision.
CORRELATION_REVIEW_STATUSES = ("candidate", "confirmed", "rejected")


class EventCorrelation(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "event_correlations"
    __table_args__ = (
        # correlation_service always stores the pair with event_a_id <
        # event_b_id (lexicographically) before insert, so this
        # constraint actually prevents the same pair+rule being stored
        # twice, rather than missing the reverse-order duplicate.
        UniqueConstraint("event_a_id", "event_b_id", "rule_version", name="uq_event_correlations_pair_rule"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    event_a_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    event_b_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)

    # Machine-readable reason codes (e.g. "shared_source_id",
    # "temporal_proximity", "spatial_proximity") -- always explainable,
    # never a bare unexplained score. See docs/analytics/EVENT_CORRELATION.md.
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    rule_version: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    temporal_delta_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spatial_delta_meters: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # A documented 0-1 strength measure (see correlation_service.py's
    # module docstring for exactly what it does and does not mean) --
    # never presented to analysts as a probability of truth.
    match_strength: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate", index=True)
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    # Identifies which "recompute" run produced this row -- an explicit,
    # auditable operation, never an automatic background merge.
    correlation_batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
