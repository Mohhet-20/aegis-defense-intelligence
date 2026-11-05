from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.inference_job import INFERENCE_JOB_TYPES


class SubmitInferenceJobRequest(BaseModel):
    media_asset_id: str
    model_record_id: str
    job_type: str
    confidence_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    nms_iou_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    frame_sample_interval_seconds: Optional[float] = Field(default=None, gt=0.0)
    # No upper bound here, deliberately: the real cap is always
    # settings.CV_VIDEO_MAX_FRAMES_PER_JOB, enforced unconditionally by
    # inference_service.submit_inference_job()'s own min() clamp
    # regardless of what a client requests. An upper `le` here would
    # make the API *reject* an over-large request instead of
    # *clamping* it -- exactly the bug found and fixed for
    # GET /fusion/graph's max_depth/max_nodes.
    max_frames: Optional[int] = Field(default=None, ge=1)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)

    @field_validator("job_type")
    @classmethod
    def _check_job_type(cls, v: str) -> str:
        if v not in INFERENCE_JOB_TYPES:
            raise ValueError(f"job_type must be one of {INFERENCE_JOB_TYPES}")
        return v


class InferenceJobResponse(BaseModel):
    id: str
    organization_id: str
    media_asset_id: str
    model_record_id: str
    job_type: str
    status: str
    parameters: dict
    frames_processed: int
    detections_created: int
    idempotency_key: Optional[str]
    retry_count: int
    retried_from_job_id: Optional[str]
    triggered_by_user_id: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
