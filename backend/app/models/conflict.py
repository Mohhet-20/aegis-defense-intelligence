"""Conflict. Records a detected contradiction
between two events that are already known to be related (they have an
existing `EventCorrelation` row) -- e.g. one reports a materially
different location, a different event_type, or a different value for
the same attribute key than the other.

Conflict detection is deliberately conservative: a field one side
simply never reported is NEVER a conflict (missing information is not
negative evidence, Section 9). A conflict is only ever an actual,
comparable disagreement between two present values.

Resolving a conflict NEVER rewrites the original `Event` rows to make
them agree -- see docs/analytics/CONFLICT_DETECTION.md. "corrected"
below means an analyst has recorded that a separately-audited
correction exists elsewhere (e.g. a newer, reviewed event supersedes
the disputed one) -- not that this platform silently edited history.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

CONFLICT_REVIEW_STATUSES = ("unresolved", "explained", "accepted", "corrected", "superseded")


class Conflict(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "conflicts"
    __table_args__ = (
        UniqueConstraint("event_a_id", "event_b_id", "conflict_rule_version", name="uq_conflicts_pair_rule"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    event_a_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    event_b_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    # The correlation candidate this conflict was found inside, if any
    # -- conflicts are only ever evaluated between events already
    # flagged related by correlation_service, never an independent
    # all-pairs scan. NULL only if that correlation row is later deleted
    # (never happens today, since nothing deletes correlations).
    correlation_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("event_correlations.id", ondelete="SET NULL"), nullable=True, index=True)

    # [{"field": "...", "value_a": ..., "value_b": ..., "rule": "..."}]
    # -- always the exact two values that disagree and which rule
    # flagged them, never an unexplained flag.
    conflicting_fields: Mapped[list] = mapped_column(JSON, default=list)
    conflict_rule_version: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unresolved", index=True)
    resolved_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    fusion_batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
