from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class DetectionResultResponse(BaseModel):
    id: str
    organization_id: str
    inference_job_id: str
    media_asset_id: str
    model_record_id: str
    schema_version: str
    frame_index: Optional[int]
    frame_timestamp_seconds: Optional[float]
    class_label: str
    confidence: float
    bbox_x_min: float
    bbox_y_min: float
    bbox_x_max: float
    bbox_y_max: float
    review_status: str
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[datetime]
    review_note: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class DetectionReviewRequest(BaseModel):
    review_status: str
    review_note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("review_status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in ("confirmed", "rejected"):
            raise ValueError("review_status must be 'confirmed' or 'rejected'")
        return v


class PromoteToEvidenceRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    summary: Optional[str] = Field(default=None, max_length=2000)
