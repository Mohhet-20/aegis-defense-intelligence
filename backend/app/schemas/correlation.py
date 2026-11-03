from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.event_correlation import CORRELATION_REVIEW_STATUSES


class EventCorrelationResponse(BaseModel):
    id: str
    organization_id: str
    event_a_id: str
    event_b_id: str
    reasons: list[str]
    rule_version: str
    temporal_delta_seconds: Optional[float]
    spatial_delta_meters: Optional[float]
    match_strength: Optional[float]
    review_status: str
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[datetime]
    correlation_batch_id: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class CorrelationReviewRequest(BaseModel):
    review_status: str

    @field_validator("review_status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        allowed = set(CORRELATION_REVIEW_STATUSES) - {"candidate"}
        if v not in allowed:
            raise ValueError(f"review_status must be one of {sorted(allowed)} -- a review is a human decision, never set back to 'candidate'")
        return v


class RecomputeCorrelationsRequest(BaseModel):
    time_window_seconds: Optional[int] = Field(default=None, ge=1, le=7 * 24 * 3600)
    spatial_threshold_meters: Optional[float] = Field(default=None, ge=0.0, le=100_000.0)


class RecomputeCorrelationsResponse(BaseModel):
    batch_id: str
    events_considered: int
    pairs_considered: int
    correlations_created: int
    already_existed: int
    rule_version: str
    time_window_seconds: int
    spatial_threshold_meters: float
