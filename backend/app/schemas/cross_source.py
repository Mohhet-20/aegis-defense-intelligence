from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CrossSourceCompareRequest(BaseModel):
    observation_a_id: str
    observation_b_id: str
    tolerance: Optional[float] = Field(default=None, ge=0)


class CrossSourceComparisonResponse(BaseModel):
    method_version: str
    observation_a_id: str
    observation_b_id: str
    sensor_a_id: Optional[str]
    sensor_b_id: Optional[str]
    measurement_type_a: str
    measurement_type_b: str
    same_measurement_type: bool
    unit_a: Optional[str]
    unit_b: Optional[str]
    units_compatible: bool
    value_a: Optional[float]
    value_b: Optional[float]
    value_b_converted_to_unit_a: Optional[float]
    delta: Optional[float]
    tolerance: Optional[float]
    conflicting: Optional[bool]
    missing_a: bool
    missing_b: bool
    time_gap_seconds: float
    observed_at_a: datetime
    observed_at_b: datetime
    provenance_a: dict
    provenance_b: dict
    explanation: str


class CrossSourceLinkRequest(BaseModel):
    observation_a_id: str
    observation_b_id: str
    tolerance: Optional[float] = Field(default=None, ge=0)
