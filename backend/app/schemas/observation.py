from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.schemas.common import GeoLocationResponseFields


class ObservationResponse(GeoLocationResponseFields):
    id: str
    organization_id: str
    sensor_id: Optional[str]
    source_id: Optional[str]
    observed_at: datetime
    observation_type: str
    payload: dict
    quality_metadata: dict
    provenance: dict
    processing_status: str
    data_origin: str
    created_at: datetime
    updated_at: datetime

    # --- Additions --------------------------------
    ingested_at: Optional[datetime]
    measurement_value: Optional[float]
    unit: Optional[str]
    validation_status: str
    quality_flags: list
    source_record_id: Optional[str]
    ingestion_job_id: Optional[str]
    schema_version: str
    calibration_metadata: Optional[dict]
    uncertainty_metadata: Optional[dict]

    model_config = {"from_attributes": True}
