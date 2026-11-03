"""FusionJob. Tracks one explicit, authorized
run of the fusion pipeline: correlation recompute + conflict detection,
composed by `app/services/fusion_service.py`. Same spirit as Phase 2's
`IngestionJob` -- a real, inspectable record of what a run actually did
(counts, parameters, errors), never a silent background process.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

FUSION_JOB_STATUSES = ("running", "completed", "failed")


class FusionJob(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "fusion_jobs"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    triggered_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    rule_version: Mapped[str] = mapped_column(String(20), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)

    events_considered: Mapped[int] = mapped_column(nullable=False, default=0)
    correlations_created: Mapped[int] = mapped_column(nullable=False, default=0)
    conflicts_created: Mapped[int] = mapped_column(nullable=False, default=0)

    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
