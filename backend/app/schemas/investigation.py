from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.investigation import (
    INVESTIGATION_PRIORITIES,
    INVESTIGATION_REVIEW_STATUSES,
    INVESTIGATION_STATUSES,
)


class InvestigationCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=4000)
    priority: str = Field(default="normal")
    assigned_user_id: Optional[str] = None
    linked_event_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    purpose: Optional[str] = Field(default=None, max_length=2000)
    scope: Optional[str] = Field(default=None, max_length=2000)
    collaborator_user_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, max_length=20)
    is_restricted: bool = False
    initial_status: str = "open"

    @field_validator("initial_status")
    @classmethod
    def _check_initial(cls, v: str) -> str:
        if v not in ("draft", "open"):
            raise ValueError("initial_status must be 'draft' or 'open'")
        return v

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(t.strip().lower() for t in v if t.strip() and len(t) <= 50))

    @field_validator("priority")
    @classmethod
    def _check_priority(cls, v: str) -> str:
        if v not in INVESTIGATION_PRIORITIES:
            raise ValueError(f"priority must be one of {INVESTIGATION_PRIORITIES}")
        return v


class InvestigationUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = Field(default=None, max_length=4000)
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_user_id: Optional[str] = None
    linked_event_ids: Optional[list[str]] = None
    evidence_refs: Optional[list[str]] = None
    review_status: Optional[str] = None
    resolution_notes: Optional[str] = Field(default=None, max_length=4000)
    purpose: Optional[str] = Field(default=None, max_length=2000)
    scope: Optional[str] = Field(default=None, max_length=2000)
    collaborator_user_ids: Optional[list[str]] = None
    tags: Optional[list[str]] = Field(default=None, max_length=20)
    is_restricted: Optional[bool] = None
    closure_reason: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in INVESTIGATION_STATUSES:
            raise ValueError(f"status must be one of {INVESTIGATION_STATUSES}")
        return v

    @field_validator("priority")
    @classmethod
    def _check_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in INVESTIGATION_PRIORITIES:
            raise ValueError(f"priority must be one of {INVESTIGATION_PRIORITIES}")
        return v

    @field_validator("review_status")
    @classmethod
    def _check_review_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in INVESTIGATION_REVIEW_STATUSES:
            raise ValueError(f"review_status must be one of {INVESTIGATION_REVIEW_STATUSES}")
        return v


class InvestigationResponse(BaseModel):
    id: str
    organization_id: str
    title: str
    description: Optional[str]
    status: str
    priority: str
    assigned_user_id: Optional[str]
    linked_event_ids: list
    evidence_refs: list
    review_status: str
    resolution_notes: Optional[str]
    purpose: Optional[str]
    scope: Optional[str]
    collaborator_user_ids: list
    tags: list = []
    closure_reason: Optional[str] = None
    closed_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    is_restricted: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
