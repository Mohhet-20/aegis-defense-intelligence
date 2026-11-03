from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RunEvaluationRequest(BaseModel):
    model_record_id: str
    sample_count: int = Field(default=20, ge=1, le=200)
    iou_match_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    # synthetic_single_rectangle_fixture: generated geometry (pipeline check).
    # coco_val2017_subset: real photographs (scripts/fetch_eval_data.py must have run).
    dataset: Literal["synthetic_single_rectangle_fixture", "coco_val2017_subset"] = "synthetic_single_rectangle_fixture"


class ModelEvaluationRunResponse(BaseModel):
    id: str
    organization_id: str
    model_record_id: str
    dataset_name: str
    dataset_version: str
    is_synthetic: bool
    sample_count: int
    iou_match_threshold: float
    precision: float
    recall: float
    f1_score: float
    mean_iou: float
    metrics_detail: dict
    notes: Optional[str]
    evaluated_by_user_id: Optional[str]
    evaluated_at: datetime

    model_config = {"from_attributes": True}
