"""The versioned edge synchronization protocol envelope (Section 9), plus the admin-facing shapes for inspecting the sync queue
and conflicts. These Pydantic models ARE the documented protocol --
`app/edge/simulator.py` (the in-process simulated edge runtime, see
docs/architecture/EDGE_ARCHITECTURE.md Section 2) imports the same
classes to construct a real request, rather than a second,
independently-maintained copy of the shapes drifting out of sync with
what the API actually accepts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

EDGE_SYNC_PROTOCOL_VERSION = "edge_sync_v1"
SUPPORTED_EDGE_SYNC_PROTOCOL_VERSIONS = (EDGE_SYNC_PROTOCOL_VERSION,)

# Bounded batch size ("maximum queue batch size") -- a
# single sync request can never ask the server to process an unbounded
# number of records.
MAX_BATCH_SIZE = 100


class SyncRecordEnvelope(BaseModel):
    """One logical record a device wants synced. `message_id` identifies
    THIS ATTEMPT; `idempotency_key` identifies the LOGICAL OPERATION and
    must stay identical across retries of the same record (Section 5:
    "a stable idempotency key for each logical operation")."""

    message_id: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=150)
    record_type: str
    client_record_id: str = Field(min_length=1, max_length=150)
    schema_version: str = Field(min_length=1, max_length=20)
    payload: dict
    payload_hash: Optional[str] = Field(default=None, max_length=64)
    source_created_at: datetime
    queued_at: datetime
    # Only meaningful (and required by edge_sync_service) for a MUTABLE
    # record_type such as "annotation" -- the revision this submission
    # was based on, used for optimistic-concurrency conflict detection.
    # Omitted entirely for an immutable/append-only
    # record_type.
    base_revision: Optional[int] = None


class SyncBatchRequest(BaseModel):
    protocol_version: str
    device_id: str = Field(min_length=1, max_length=100)
    batch_id: Optional[str] = Field(default=None, max_length=100)
    sent_at: datetime
    records: list[SyncRecordEnvelope] = Field(max_length=MAX_BATCH_SIZE)


class SyncRecordAckResponse(BaseModel):
    message_id: str
    idempotency_key: str
    client_record_id: str
    sync_record_id: str
    sync_status: str
    error_category: Optional[str] = None
    error_message: Optional[str] = None
    conflict_id: Optional[str] = None
    # float, not int -- edge_sync_service.compute_backoff_seconds()
    # applies jitter, so this is deliberately sub-second-precise rather
    # than rounded to a whole second.
    retry_after_seconds: Optional[float] = None


class SyncBatchResponse(BaseModel):
    protocol_version: str
    batch_id: Optional[str]
    accepted_count: int
    conflict_count: int
    quarantined_count: int
    rejected_count: int
    results: list[SyncRecordAckResponse]


class HealthReportRequest(BaseModel):
    protocol_version: str
    reported_at: datetime
    connectivity_state: str
    resource_metrics: Optional[dict] = None
    queue_depth: int = Field(ge=0)
    pending_sync_count: int = Field(ge=0)
    model_status: Optional[dict] = None
    software_version: Optional[str] = Field(default=None, max_length=50)
    runtime_capabilities: Optional[list[str]] = None


class HealthReportAckResponse(BaseModel):
    report_id: str
    received_at: datetime


# --- Admin-facing (user-JWT-authenticated) views ---------------------


class SyncRecordResponse(BaseModel):
    id: str
    device_id: str
    message_id: str
    idempotency_key: str
    batch_id: Optional[str]
    protocol_version: str
    schema_version: str
    record_type: str
    client_record_id: str
    base_revision: Optional[int]
    revision: Optional[int]
    payload_hash: Optional[str]
    source_created_at: datetime
    queued_at: datetime
    processed_at: Optional[datetime]
    acknowledged_at: Optional[datetime]
    sync_status: str
    retry_count: int
    next_retry_at: Optional[datetime]
    last_error_category: Optional[str]
    last_error_message: Optional[str]
    supersedes_sync_record_id: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class SyncQueueStatusCount(BaseModel):
    sync_status: str
    count: int


class SyncQueueSummaryResponse(BaseModel):
    """Section 15's observability numbers -- every count here is a real
    query result, never a fabricated/sample figure. A field left out
    (rather than zeroed) means it genuinely could not be computed, per
    Section 15's "mark unavailable instead of displaying fabricated
    zeros" -- in practice every field here IS always computable from
    SyncRecord directly, so none are ever omitted; this note documents
    why that's true rather than coincidental."""

    total_records: int
    by_status: list[SyncQueueStatusCount]
    oldest_pending_age_seconds: Optional[float]
    unresolved_conflict_count: int
    quarantined_count: int
    devices_with_pending_records: int


class SyncRecordRetryRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)


# --- Conflicts ---------------------------------------------------------


class SyncConflictResponse(BaseModel):
    id: str
    device_id: str
    sync_record_id: str
    record_type: str
    client_record_id: str
    conflict_reason: str
    local_version: dict
    central_version: dict
    resolution_status: str
    resolution_strategy: Optional[str]
    resolved_by_user_id: Optional[str]
    resolved_at: Optional[datetime]
    resolution_note: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class SyncConflictResolveRequest(BaseModel):
    resolution_strategy: str
    resolution_note: Optional[str] = Field(default=None, max_length=2000)
