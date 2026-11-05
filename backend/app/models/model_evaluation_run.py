"""ModelEvaluationRun. One recorded evaluation of
one ModelRecord/model-version against one named, versioned labelled
dataset -- precision/recall/F1/mean IoU, always traceable to the exact
dataset name+version and model_record_id+version that produced them
("metrics always traceable to exact dataset+model
versions"). Never a bare number with no attribution, same principle
the AI_ANALYTICS_CONTRACTS.md already states for RiskAssessment.

`is_synthetic=True` means the dataset is a clearly-labelled synthetic
fixture built for this repository (see
backend/tests/fixtures/cv_eval/README.md) because no real labelled
operational dataset exists yet -- Section 10 explicitly permits this as
long as it is never presented as a real-world accuracy measurement. See
docs/ml/MODEL_EVALUATION.md.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime


class ModelEvaluationRun(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "model_evaluation_runs"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    model_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("model_records.id", ondelete="CASCADE"), nullable=False, index=True)

    dataset_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(50), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)

    iou_match_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    precision: Mapped[float] = mapped_column(Float, nullable=False)
    recall: Mapped[float] = mapped_column(Float, nullable=False)
    f1_score: Mapped[float] = mapped_column(Float, nullable=False)
    mean_iou: Mapped[float] = mapped_column(Float, nullable=False)

    # Per-sample / per-class breakdown -- never required to interpret
    # the four headline numbers above, but preserved for an analyst who
    # wants to see exactly which fixture samples the model missed.
    metrics_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    evaluated_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
