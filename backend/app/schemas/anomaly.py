from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.observation_anomaly import ANOMALY_REVIEW_STATUSES


class AnomalyRunRequest(BaseModel):
    sensor_id: str
    measurement_type: str


class ObservationAnomalyResponse(BaseModel):
    id: str
    organization_id: str
    sensor_id: str
    measurement_type: str
    observation_id: Optional[str]
    window_start: Optional[datetime]
    window_end: Optional[datetime]
    detection_method: str
    method_version: str
    config: dict
    observed_value: Optional[float]
    observed_summary: dict
    baseline_summary: Optional[dict]
    explanation: str
    severity: str
    category: str
    quality_flags: list
    review_status: str
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[datetime]
    review_note: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class AnomalyRunResponse(BaseModel):
    created: list[ObservationAnomalyResponse]
    already_known: list[ObservationAnomalyResponse]
    insufficient_baseline: dict[str, str]


class AnomalyReviewRequest(BaseModel):
    review_status: str
    review_note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("review_status")
    @classmethod
    def _check_review_status(cls, v: str) -> str:
        if v not in ANOMALY_REVIEW_STATUSES:
            raise ValueError(f"review_status must be one of {ANOMALY_REVIEW_STATUSES}")
        return v
