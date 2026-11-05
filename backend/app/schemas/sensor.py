from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.sensor import SENSOR_LIFECYCLE_STATUSES, SENSOR_STATUSES
from app.schemas.common import GeoLocationFields


class SensorCreateRequest(GeoLocationFields):
    name: str = Field(min_length=1, max_length=200)
    sensor_type: str = Field(min_length=1, max_length=50)
    source_id: Optional[str] = None
    capability_metadata: dict = Field(default_factory=dict)

    # --- Additions --------------------------------
    category: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None, max_length=2000)
    manufacturer: Optional[str] = Field(default=None, max_length=200)
    model_name: Optional[str] = Field(default=None, max_length=200)
    asset_id: Optional[str] = None
    measurement_types: list[str] = Field(default_factory=list)
    measurement_units: dict[str, str] = Field(default_factory=dict)
    operating_range: dict[str, dict] = Field(default_factory=dict)
    nominal_sampling_interval_seconds: Optional[float] = Field(default=None, gt=0)
    expected_data_format: Optional[str] = Field(default=None, max_length=50)
    sensor_timezone: str = Field(default="UTC", max_length=50)


class SensorUpdateRequest(GeoLocationFields):
    name: Optional[str] = Field(default=None, max_length=200)
    status: Optional[str] = None
    capability_metadata: Optional[dict] = None

    category: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None, max_length=2000)
    manufacturer: Optional[str] = Field(default=None, max_length=200)
    model_name: Optional[str] = Field(default=None, max_length=200)
    asset_id: Optional[str] = None
    measurement_types: Optional[list[str]] = None
    measurement_units: Optional[dict[str, str]] = None
    operating_range: Optional[dict[str, dict]] = None
    nominal_sampling_interval_seconds: Optional[float] = Field(default=None, gt=0)
    expected_data_format: Optional[str] = Field(default=None, max_length=50)
    sensor_timezone: Optional[str] = Field(default=None, max_length=50)

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in SENSOR_STATUSES:
            raise ValueError(f"status must be one of {SENSOR_STATUSES}")
        return v


class SensorLifecycleTransitionRequest(BaseModel):
    new_status: str
    note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("new_status")
    @classmethod
    def _check_new_status(cls, v: str) -> str:
        if v not in SENSOR_LIFECYCLE_STATUSES:
            raise ValueError(f"new_status must be one of {SENSOR_LIFECYCLE_STATUSES}")
        return v


class SensorResponse(BaseModel):
    id: str
    organization_id: str
    source_id: Optional[str]
    name: str
    sensor_type: str
    status: str
    last_seen_at: Optional[datetime]
    latitude: Optional[float]
    longitude: Optional[float]
    capability_metadata: dict
    config_version: Optional[str]
    created_at: datetime
    updated_at: datetime

    category: Optional[str]
    description: Optional[str]
    manufacturer: Optional[str]
    model_name: Optional[str]
    asset_id: Optional[str]
    measurement_types: list
    measurement_units: dict
    operating_range: dict
    nominal_sampling_interval_seconds: Optional[float]
    expected_data_format: Optional[str]
    sensor_timezone: str
    lifecycle_status: str
    last_ingestion_success_at: Optional[datetime]
    device_reported_status: Optional[str]
    device_reported_status_at: Optional[datetime]
    retired_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ConnectivityHealthResponse(BaseModel):
    status: str
    last_valid_observation_at: Optional[datetime]
    last_ingestion_success_at: Optional[datetime]
    explanation: str


class MeasurementQualityHealthResponse(BaseModel):
    status: str
    sample_size: int
    invalid_count: int
    invalid_rate: Optional[float]
    warning_rate: Optional[float]
    explanation: str


class AnomalyStatusHealthResponse(BaseModel):
    unresolved_count: int
    by_severity: dict
    explanation: str


class DeviceReportedHealthResponse(BaseModel):
    status: Optional[str]
    as_of: Optional[datetime]
    explanation: str


class SensorHealthResponse(BaseModel):
    sensor_id: str
    as_of: datetime
    rule_version: str
    connectivity: ConnectivityHealthResponse
    measurement_quality: MeasurementQualityHealthResponse
    anomaly_status: AnomalyStatusHealthResponse
    device_reported: DeviceReportedHealthResponse
