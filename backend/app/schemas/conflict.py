from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.conflict import CONFLICT_REVIEW_STATUSES


class ConflictResolveRequest(BaseModel):
    review_status: str
    resolution_note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("review_status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in CONFLICT_REVIEW_STATUSES:
            raise ValueError(f"review_status must be one of {CONFLICT_REVIEW_STATUSES}")
        return v


class ConflictResponse(BaseModel):
    id: str
    organization_id: str
    event_a_id: str
    event_b_id: str
    correlation_id: Optional[str]
    conflicting_fields: list
    conflict_rule_version: str
    review_status: str
    resolved_by_user_id: Optional[str]
    resolved_at: Optional[datetime]
    resolution_note: Optional[str]
    fusion_batch_id: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class DetectConflictsRequest(BaseModel):
    correlation_batch_id: Optional[str] = None
    spatial_conflict_threshold_meters: Optional[float] = Field(default=None, ge=0.0, le=200_000.0)


class DetectConflictsResponse(BaseModel):
    batch_id: str
    pairs_considered: int
    conflicts_created: int
    conflicts_updated: int
    rule_version: str
