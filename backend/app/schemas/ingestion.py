from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class IngestionJobResponse(BaseModel):
    id: str
    organization_id: str
    source_id: str
    created_by_user_id: Optional[str]
    job_type: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    accepted_count: int
    rejected_count: int
    skipped_count: int
    duplicate_count: int
    error_summary: list
    trigger_type: str
    retry_count: int
    correlation_id: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
