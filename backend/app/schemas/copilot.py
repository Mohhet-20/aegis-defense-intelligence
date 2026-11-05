"""Request/response schemas for retrieval search and the copilot."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

RecordType = Literal["investigation", "investigation_note", "event", "observation", "assessment", "assessment_review",
                     "evidence", "data_source", "media_asset", "scenario"]
Task = Literal["question", "summarize_investigation", "chronology", "compare", "report_draft", "related"]


class RecordRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_type: RecordType
    record_id: str = Field(min_length=1, max_length=36)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: Task = "question"
    question: Optional[str] = Field(default=None, max_length=4000)
    investigation_id: Optional[str] = Field(default=None, max_length=36)
    record_types: Optional[list[RecordType]] = Field(default=None, max_length=10)
    record_refs: Optional[list[RecordRef]] = Field(default=None, max_length=6)
    conversation_id: Optional[str] = Field(default=None, max_length=36)
    save: bool = True
    title: Optional[str] = Field(default=None, max_length=200)
    report_title: Optional[str] = Field(default=None, max_length=200)


class VerifyCitationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = Field(default=None, max_length=20)
    record_type: str = Field(max_length=30)
    record_id: str = Field(max_length=36)
    document_version: Optional[int] = Field(default=None, ge=1)
    chunk_position: Optional[int] = Field(default=None, ge=0)
    section: Optional[str] = Field(default=None, max_length=200)
    quote: Optional[str] = Field(default=None, max_length=2000)


class VerifyCitationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citations: list[VerifyCitationItem] = Field(min_length=1, max_length=50)


class IndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_types: Optional[list[RecordType]] = None
    investigation_id: Optional[str] = Field(default=None, max_length=36)


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = Field(default=None, max_length=200)
    investigation_id: Optional[str] = Field(default=None, max_length=36)


class SearchHit(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    record_type: str
    record_id: str
    document_id: str
    chunk_id: str
    chunk_position: int
    document_version: int
    title: Optional[str]
    section: Optional[str]
    excerpt: str
    score: float
    matched_terms: list[str]
    matching_chunks: int
    source_time: Optional[str]
    source_id: Optional[str]
    review_status: Optional[str]
    investigation_id: Optional[str]
    source_ref: str
    extraction_method: str
    content_available: bool
    stale: bool
    link: Optional[str]


class SearchResponse(BaseModel):
    items: list[SearchHit]
    total: int
    page: int
    page_size: int
    query_terms: list[str]
    candidates_truncated: bool
    notice: Optional[str]
    filters_applied: dict[str, Any]
    method: dict[str, Any]


class Claim(BaseModel):
    id: str
    text: str
    kind: Literal["source_statement", "record_summary", "generated_summary", "system_note"]
    citation_ids: list[str]
    support: Optional[str] = None
    support_ratio: Optional[float] = None
    withheld: Optional[bool] = None
    source_changed: Optional[bool] = None


class Citation(BaseModel):
    id: Optional[str] = None
    record_type: str
    record_id: str
    document_version: Optional[int] = None
    chunk_position: Optional[int] = None
    title: Optional[str] = None
    section: Optional[str] = None
    quote: Optional[str] = None
    source_time: Optional[str] = None
    link: Optional[str] = None
    status: Literal["verified", "source_changed", "unavailable", "access_revoked", "unverified"]
    status_note: Optional[str] = None


class AnswerResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    task: str
    mode: Literal["extractive", "generative", "deterministic"]
    status: str
    generation: dict[str, Any]
    claims: list[Claim]
    citations: list[Citation]
    uncertainty: list[str]
    missing_information: list[str]
    conflicts: list[dict[str, Any]]
    followups: list[str]
    records_used: list[dict[str, Any]]
    retrieval: dict[str, Any]
    generated_at: str


class AskResponse(BaseModel):
    answer: AnswerResponse
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None


class VerifyCitationsResponse(BaseModel):
    citations: list[Citation]


class ConversationSummary(BaseModel):
    id: str
    title: Optional[str]
    investigation_id: Optional[str]
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    total: int
    page: int
    page_size: int


class ConversationMessage(BaseModel):
    id: str
    role: str
    content: Optional[str]
    task: Optional[str]
    created_at: datetime
    answer_mode: Optional[str]
    answer: Optional[dict[str, Any]]


class ConversationDetail(BaseModel):
    id: str
    title: Optional[str]
    investigation_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessage]
    notice: str
