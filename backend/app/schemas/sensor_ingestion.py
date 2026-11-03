from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SensorBatchSubmitRequest(BaseModel):
    source_id: str
    format: str = Field(pattern="^(json|csv)$")
    # Base64 is NOT used here -- the HTTP route accepts a multipart file
    # upload, same convention as Phase 1's /ingestion/upload. This
    # schema documents the non-file fields only; see
    # app/api/routes/sensor_ingestion.py.


class SyntheticSensorBatchRequest(BaseModel):
    source_id: str
    sensor_id: str
    measurement_type: str
    unit: Optional[str] = None
    count: int = Field(default=20, ge=1, le=2000)
    seed: int = 0
    base_value: float = 20.0
    noise_amplitude: float = Field(default=0.5, ge=0)
    interval_seconds: float = Field(default=60.0, gt=0)
    start_at: Optional[datetime] = None
    value_overrides: dict[str, float] = Field(default_factory=dict)
    skip_indices: list[int] = Field(default_factory=list)


class SensorIngestionJobResponse(BaseModel):
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


class SensorRawRecordResponse(BaseModel):
    id: str
    organization_id: str
    source_id: str
    ingestion_job_id: Optional[str]
    external_record_id: Optional[str]
    connector_type: str
    connector_version: str
    content_fingerprint: str
    payload: dict
    received_at: datetime
    validation_status: str
    validation_errors: list
    validation_warnings: list
    is_duplicate: bool
    duplicate_reason: Optional[str]

    model_config = {"from_attributes": True}
