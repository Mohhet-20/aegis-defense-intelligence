from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field



class TransitionRequest(BaseModel):
    to_status: str
    reason: Optional[str] = Field(default=None, max_length=2000)


class ReasonRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)


class MemberRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    role: str = "member"


class MemberResponse(BaseModel):
    id: str
    user_id: str
    role: str
    created_at: datetime
    model_config = {"from_attributes": True}


class StatusHistoryResponse(BaseModel):
    id: str
    from_status: Optional[str]
    to_status: str
    reason: Optional[str]
    changed_by_user_id: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}


class LinkRequest(BaseModel):
    record_type: str = Field(min_length=1, max_length=30)
    record_id: str = Field(min_length=1, max_length=36)
    note: Optional[str] = Field(default=None, max_length=1000)


class LinkResponse(BaseModel):
    id: str
    record_type: str
    record_id: str
    note: Optional[str]
    created_at: datetime
    linked_by_user_id: Optional[str]
    summary: Optional[dict] = None
    resolvable: bool = True


class RegisterEvidenceRequest(BaseModel):
    evidence_type: str
    title: str = Field(min_length=1, max_length=300)
    summary: Optional[str] = Field(default=None, max_length=2000)
    record_id: Optional[str] = Field(default=None, max_length=36)
    record_version: Optional[int] = Field(default=None, ge=1)
    event_id: Optional[str] = Field(default=None, max_length=36)
    observation_id: Optional[str] = Field(default=None, max_length=36)
    raw_record_id: Optional[str] = Field(default=None, max_length=36)
    content: Optional[str] = Field(default=None, max_length=8000)
    external_reference_uri: Optional[str] = Field(default=None, max_length=2000)
    claimed_hash: Optional[str] = Field(default=None, max_length=128)
    access_classification: str = "internal"
    captured_at: Optional[datetime] = None
    processing_version: Optional[str] = Field(default=None, max_length=100)


class EvidenceDetailResponse(BaseModel):
    id: str
    evidence_type: str
    title: str
    summary: Optional[str]
    event_id: Optional[str]
    observation_id: Optional[str]
    raw_record_id: Optional[str]
    media_asset_id: Optional[str]
    detection_result_id: Optional[str]
    source_id: Optional[str]
    external_reference_uri: Optional[str]
    content: Optional[str]
    integrity_hash: Optional[str]
    integrity_hash_algorithm: Optional[str]
    hash_recorded_at: Optional[datetime]
    access_classification: str
    review_status: str
    captured_at: Optional[datetime]
    processing_version: Optional[str]
    supersedes_evidence_id: Optional[str]
    superseded_by_evidence_id: Optional[str]
    created_by_user_id: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}


class RegisterEvidenceResponse(BaseModel):
    evidence: EvidenceDetailResponse
    reused_existing: bool
    link_id: str


class ReviewStatusRequest(BaseModel):
    review_status: str
    note: Optional[str] = Field(default=None, max_length=1000)


class SupersedeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    title: Optional[str] = Field(default=None, max_length=300)
    summary: Optional[str] = Field(default=None, max_length=2000)
    content: Optional[str] = Field(default=None, max_length=8000)


class IntegrityCheckResponse(BaseModel):
    id: str
    evidence_id: str
    result: str
    algorithm: Optional[str]
    recorded_hash: Optional[str]
    computed_hash: Optional[str]
    detail: Optional[str]
    checked_by_user_id: Optional[str]
    created_at: datetime
    disclaimer: Optional[str] = None
    model_config = {"from_attributes": True}


class NoteCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    note_kind: str = "analyst_interpretation"
    tags: list[str] = Field(default_factory=list, max_length=20)
    category: Optional[str] = Field(default=None, max_length=50)
    evidence_id: Optional[str] = Field(default=None, max_length=36)
    parent_note_id: Optional[str] = Field(default=None, max_length=36)
    assignee_user_id: Optional[str] = Field(default=None, max_length=36)


class NoteUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    body: Optional[str] = Field(default=None, max_length=8000)
    note_kind: Optional[str] = None
    tags: Optional[list[str]] = Field(default=None, max_length=20)
    category: Optional[str] = Field(default=None, max_length=50)
    assignee_user_id: Optional[str] = Field(default=None, max_length=36)
    resolution_status: Optional[str] = None
    change_summary: Optional[str] = Field(default=None, max_length=500)


class NoteResponse(BaseModel):
    id: str
    investigation_id: str
    evidence_id: Optional[str]
    parent_note_id: Optional[str]
    note_kind: str
    body: str
    tags: list
    category: Optional[str]
    author_user_id: Optional[str]
    assignee_user_id: Optional[str]
    resolution_status: Optional[str]
    resolved_by_user_id: Optional[str]
    resolved_at: Optional[datetime]
    version: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class NoteRevisionResponse(BaseModel):
    version: int
    note_kind: str
    body: str
    tags: list
    changed_by_user_id: Optional[str]
    change_summary: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}
