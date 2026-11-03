from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.track_annotation import ANNOTATION_TYPES


class TrackAnnotationCreateRequest(BaseModel):
    annotation_type: str
    note: Optional[str] = Field(default=None, max_length=2000)
    # Set this to correct/supersede an earlier annotation on the SAME
    # track -- the earlier row is never edited or deleted, only marked
    # superseded_at (Section 3E: "Preserve annotation history when a
    # decision is corrected").
    supersedes_annotation_id: Optional[str] = None

    @field_validator("annotation_type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in ANNOTATION_TYPES:
            raise ValueError(f"annotation_type must be one of {ANNOTATION_TYPES}")
        return v


class TrackAnnotationResponse(BaseModel):
    id: str
    track_id: str
    annotation_type: str
    note: Optional[str]
    created_by_user_id: Optional[str]
    supersedes_annotation_id: Optional[str]
    superseded_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}
