"""TrackingEvaluationRun. Computes real
track-level precision/recall, identity-switch count, and fragmentation
for one tracker/configuration -- always against a deterministic
SYNTHETIC multi-object fixture (app/tracking/synthetic_fixture.py),
because no real, labelled, multi-object tracking dataset exists in
this repository. Every row stamps `is_synthetic=True` for exactly the
same honesty reason the `ModelEvaluationRun` always does.

HOTA/IDF1/MOTA are deliberately NOT computed here -- Section 13 permits
them "only if a correct, documented implementation or trusted
evaluation library is available," and neither exists in this
environment (no `motmetrics`-equivalent package is installed, and
hand-rolling one of these specific, easy-to-get-subtly-wrong metrics
without a trusted reference to validate against would risk presenting
a confidently wrong number as a real measurement). See
docs/ml/TRACKING_EVALUATION.md for the full accounting of what is and
is not computed, and why.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime


class TrackingEvaluationRun(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "tracking_evaluation_runs"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    tracker_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tracker_version: Mapped[str] = mapped_column(String(20), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    dataset_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(20), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sequence_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Real, computed metrics -- precision/recall at the track level,
    # identity switches, fragmentation, mostly-tracked/mostly-lost
    # ratios, mean association IoU of matched observations. See
    # app/tracking/evaluation.py for the exact definitions used.
    track_precision: Mapped[float] = mapped_column(Float, nullable=False)
    track_recall: Mapped[float] = mapped_column(Float, nullable=False)
    identity_switches: Mapped[int] = mapped_column(Integer, nullable=False)
    fragmentation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mostly_tracked_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    mostly_lost_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    mean_association_iou: Mapped[float] = mapped_column(Float, nullable=False)

    metrics_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    evaluated_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
