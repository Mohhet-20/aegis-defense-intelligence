from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_key: str = Field(min_length=1, max_length=40)
    title: Optional[str] = Field(default=None, max_length=200)
    format: str = Field(default="json", pattern="^(json|csv|html)$")
    sections: Optional[list[str]] = Field(default=None, max_length=12)  # custom template only
    days: Optional[int] = Field(default=None, ge=1, le=366)
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    bucket: str = Field(default="auto", pattern="^(auto|hour|day)$")
    time_basis: str = Field(default="event", pattern="^(event|ingestion)$")
    source_id: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = Field(default=None, max_length=100)
    include_archived: bool = False
    notes: Optional[str] = Field(default=None, max_length=20000)  # hard cap enforced again by REPORT_MAX_NOTES_CHARS
    visibility: str = Field(default="private", pattern="^(private|organization)$")
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:\-]+$")

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        if v is not None and not v.strip():
            raise ValueError("title cannot be blank")
        return v


class ReportOut(BaseModel):
    id: str
    template_key: str
    title: str
    status: str
    format: str
    visibility: str
    parameters: dict
    has_commentary: bool
    required_permissions: list[str]
    definition_version: str
    created_by_user_id: Optional[str] = None
    created_at: datetime
    started_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    sample_summary: dict
    section_status: dict
    artifact_name: Optional[str] = None
    artifact_bytes: Optional[int] = None
    content_sha256: Optional[str] = None
    integrity_note: str
    download_count: int
    error_category: Optional[str] = None
    error_message: Optional[str] = None
    replayed: bool = False
    downloadable: bool
