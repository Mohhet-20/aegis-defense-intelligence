from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.evidence import EVIDENCE_TYPES


class EvidenceCreateRequest(BaseModel):
    evidence_type: str
    title: str = Field(min_length=1, max_length=300)
    summary: Optional[str] = Field(default=None, max_length=2000)
    event_id: Optional[str] = None
    raw_record_id: Optional[str] = None
    observation_id: Optional[str] = None
    content: Optional[str] = Field(default=None, max_length=8000)
    external_reference_uri: Optional[str] = Field(default=None, max_length=2000)
    integrity_hash: Optional[str] = Field(default=None, max_length=128)

    @field_validator("evidence_type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in EVIDENCE_TYPES:
            raise ValueError(f"evidence_type must be one of {EVIDENCE_TYPES}")
        return v


class EvidenceUpdateRequest(BaseModel):
    """Only the free-text fields -- see evidence_service.update_evidence_content()."""

    title: Optional[str] = Field(default=None, max_length=300)
    summary: Optional[str] = Field(default=None, max_length=2000)
    content: Optional[str] = Field(default=None, max_length=8000)


class EvidenceResponse(BaseModel):
    id: str
    organization_id: str
    evidence_type: str
    title: str
    summary: Optional[str]
    event_id: Optional[str]
    raw_record_id: Optional[str]
    observation_id: Optional[str]
    content: Optional[str]
    external_reference_uri: Optional[str]
    integrity_hash: Optional[str]
    detection_result_id: Optional[str] = None
    # Phase 11 (additive)
    media_asset_id: Optional[str] = None
    source_id: Optional[str] = None
    integrity_hash_algorithm: Optional[str] = None
    hash_recorded_at: Optional[datetime] = None
    access_classification: str = "internal"
    review_status: str = "unreviewed"
    captured_at: Optional[datetime] = None
    processing_version: Optional[str] = None
    supersedes_evidence_id: Optional[str] = None
    superseded_by_evidence_id: Optional[str] = None
    created_by_user_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
