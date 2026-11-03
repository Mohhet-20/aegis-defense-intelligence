from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.assessment import ASSESSMENT_EVIDENCE_ROLES, ASSESSMENT_STATUSES, CONFIDENCE_LEVELS


class AssessmentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    question: str = Field(min_length=1, max_length=1000)
    scope_description: Optional[str] = Field(default=None, max_length=2000)
    scope_start: Optional[datetime] = None
    scope_end: Optional[datetime] = None
    summary: Optional[str] = Field(default=None, max_length=4000)
    assumptions: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    confidence_level: Optional[str] = None
    confidence_rationale: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("confidence_level")
    @classmethod
    def _check_confidence(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in CONFIDENCE_LEVELS:
            raise ValueError(f"confidence_level must be one of {CONFIDENCE_LEVELS}")
        return v


class AssessmentUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)
    question: Optional[str] = Field(default=None, max_length=1000)
    scope_description: Optional[str] = Field(default=None, max_length=2000)
    scope_start: Optional[datetime] = None
    scope_end: Optional[datetime] = None
    summary: Optional[str] = Field(default=None, max_length=4000)
    assumptions: Optional[list[str]] = None
    information_gaps: Optional[list[str]] = None
    confidence_level: Optional[str] = None
    confidence_rationale: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = None
    change_note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ASSESSMENT_STATUSES:
            raise ValueError(f"status must be one of {ASSESSMENT_STATUSES}")
        return v


class AssessmentResponse(BaseModel):
    id: str
    organization_id: str
    title: str
    question: str
    scope_description: Optional[str]
    scope_start: Optional[datetime]
    scope_end: Optional[datetime]
    summary: Optional[str]
    assumptions: list
    information_gaps: list
    confidence_level: Optional[str]
    confidence_rationale: Optional[str]
    status: str
    version: int
    author_user_id: Optional[str]
    superseded_by_assessment_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssessmentRevisionResponse(BaseModel):
    id: str
    assessment_id: str
    version: int
    snapshot: dict
    changed_by_user_id: Optional[str]
    change_note: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class AssessmentEvidenceLinkRequest(BaseModel):
    role: str
    event_id: Optional[str] = None
    evidence_id: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in ASSESSMENT_EVIDENCE_ROLES:
            raise ValueError(f"role must be one of {ASSESSMENT_EVIDENCE_ROLES}")
        return v


class AssessmentEvidenceLinkResponse(BaseModel):
    id: str
    assessment_id: str
    event_id: Optional[str]
    evidence_id: Optional[str]
    role: str
    note: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
