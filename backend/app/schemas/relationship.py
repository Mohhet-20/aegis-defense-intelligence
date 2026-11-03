from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.evidence_relationship import (
    REFERENCEABLE_TYPES,
    RELATIONSHIP_REVIEW_STATUSES,
    RELATIONSHIP_TYPES,
)


class RelationshipCreateRequest(BaseModel):
    source_ref_type: str
    source_ref_id: str
    target_ref_type: str
    target_ref_id: str
    relationship_type: str
    explanation: str = Field(min_length=1, max_length=2000)
    supporting_metadata: dict = Field(default_factory=dict)
    # origin is always "analyst_created" for anything submitted through
    # this API -- a human filling out this form is, by definition, the
    # analyst_created case. rule_based/model_assisted relationships are
    # only ever written by fusion_service.py directly.

    @field_validator("source_ref_type", "target_ref_type")
    @classmethod
    def _check_ref_type(cls, v: str) -> str:
        if v not in REFERENCEABLE_TYPES:
            raise ValueError(f"ref_type must be one of {REFERENCEABLE_TYPES}")
        return v

    @field_validator("relationship_type")
    @classmethod
    def _check_relationship_type(cls, v: str) -> str:
        if v not in RELATIONSHIP_TYPES:
            raise ValueError(f"relationship_type must be one of {RELATIONSHIP_TYPES}")
        return v


class RelationshipReviewRequest(BaseModel):
    review_status: str
    review_note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("review_status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        allowed = set(RELATIONSHIP_REVIEW_STATUSES) - {"candidate"}
        if v not in allowed:
            raise ValueError(f"review_status must be one of {sorted(allowed)} -- a review is a human decision, never set back to 'candidate' directly (use reverse instead)")
        return v


class RelationshipReverseRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class EvidenceRelationshipResponse(BaseModel):
    id: str
    organization_id: str
    source_event_id: Optional[str]
    source_evidence_id: Optional[str]
    target_event_id: Optional[str]
    target_evidence_id: Optional[str]
    relationship_type: str
    origin: str
    explanation: str
    supporting_metadata: dict
    review_status: str
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[datetime]
    review_note: Optional[str]
    is_reversed: bool
    last_reversed_at: Optional[datetime]
    created_by_user_id: Optional[str]
    fusion_batch_id: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ReviewHistoryEntry(BaseModel):
    id: str
    action: str
    actor_user_id: Optional[str]
    outcome: str
    context_metadata: dict
    created_at: datetime

    model_config = {"from_attributes": True}
