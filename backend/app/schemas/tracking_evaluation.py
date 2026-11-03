from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RunTrackingEvaluationRequest(BaseModel):
    tracker_key: Optional[str] = None
    min_iou_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    max_missed_frames: int = Field(default=5, ge=0)
    min_hits_to_confirm: int = Field(default=2, ge=1)
    require_class_match: bool = True


class TrackingEvaluationRunResponse(BaseModel):
    id: str
    organization_id: str
    tracker_key: str
    tracker_version: str
    config: dict
    dataset_name: str
    dataset_version: str
    is_synthetic: bool
    sequence_count: int
    track_precision: float
    track_recall: float
    identity_switches: int
    fragmentation_count: int
    mostly_tracked_ratio: float
    mostly_lost_ratio: float
    mean_association_iou: float
    metrics_detail: dict
    notes: Optional[str]
    evaluated_by_user_id: Optional[str]
    evaluated_at: datetime

    model_config = {"from_attributes": True}
