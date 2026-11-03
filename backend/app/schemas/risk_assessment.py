from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.risk_assessment import RISK_HUMAN_REVIEW_STATUSES


class RiskAssessmentResponse(BaseModel):
    id: str
    organization_id: str
    subject_type: str
    subject_id: str
    assessed_at: datetime
    method: str
    model_record_id: Optional[str]
    score: float
    score_scale: str
    confidence: Optional[float]
    contributing_factors: list
    evidence_refs: list
    explanation: Optional[str]
    human_review_status: str
    reviewer_user_id: Optional[str]
    reviewed_at: Optional[datetime]
    reviewer_notes: Optional[str]
    data_origin: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RiskAssessmentReviewRequest(BaseModel):
    human_review_status: str
    reviewer_notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("human_review_status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        allowed = {s for s in RISK_HUMAN_REVIEW_STATUSES if s != "pending"}
        if v not in allowed:
            raise ValueError(f"human_review_status must be one of {sorted(allowed)}")
        return v
