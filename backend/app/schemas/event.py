from __future__ import annotations

from datetime import datetime
from typing import Optional


from app.schemas.common import GeoLocationResponseFields


class EventResponse(GeoLocationResponseFields):
    id: str
    organization_id: str
    source_id: str
    external_id: Optional[str]
    event_type: str
    title: str
    description: Optional[str]
    observed_at: datetime
    ingested_at: datetime
    asset_id: Optional[str]
    source_severity: Optional[str]
    priority: Optional[str]
    confidence: Optional[float]
    attributes: dict
    classification: str
    provenance: dict
    processing_status: str
    data_origin: str
    ingestion_job_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
