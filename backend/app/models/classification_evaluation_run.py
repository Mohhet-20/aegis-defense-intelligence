"""ClassificationEvaluationRun. One recorded
evaluation of one registered model version against one NAMED, VERSIONED,
caller-supplied labelled dataset, for classification and/or probability
estimates. Complements -- does not replace -- the detection
`ModelEvaluationRun` and the `TrackingEvaluationRun`.

Honesty rules baked into the shape:
 * `is_synthetic` is a REQUIRED declaration by the submitter; the API
   echoes a `performance_claim` that never presents a synthetic dataset
   as real-world performance, and never presents even a real dataset as
   more than "performance on this dataset".
 * `results` is populated only when `status == "completed"`. A run that
   failed internally is stored as `failed` with `results = NULL`, so a
   half-computed set of numbers can never be read as a success.
 * Undefined metrics are stored as `value: null` with a reason (see
   app/analytics/metrics.py), never as 0.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

CLASSIFICATION_EVAL_STATUSES = ("completed", "failed")


class ClassificationEvaluationRun(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "classification_evaluation_runs"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    model_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("model_records.id", ondelete="RESTRICT"), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)

    dataset_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(50), nullable=False)
    dataset_reference: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False)

    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_missing_label: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    evaluation_config: Mapped[dict] = mapped_column(JSON, default=dict)
    metric_definitions: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed", index=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    evaluated_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
