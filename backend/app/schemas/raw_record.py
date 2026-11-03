from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class RawRecordResponse(BaseModel):
    id: str
    organization_id: str
    source_id: str
    ingestion_job_id: Optional[str]
    event_id: Optional[str]
    external_record_id: Optional[str]
    connector_type: str
    connector_version: str
    normalization_version: str
    schema_version: str
    content_fingerprint: str
    payload: dict
    source_observed_at_raw: Optional[str]
    received_at: datetime
    validation_status: str
    validation_errors: list
    validation_warnings: list
    is_duplicate: bool
    duplicate_of_raw_record_id: Optional[str]
    duplicate_reason: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
