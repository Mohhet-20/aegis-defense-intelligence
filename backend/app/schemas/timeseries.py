from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TimeSeriesPointResponse(BaseModel):
    observation_id: str
    observed_at: datetime
    value: Optional[float]
    unit: Optional[str]
    validation_status: str
    quality_flags: list


class TimeSeriesResponse(BaseModel):
    sensor_id: str
    measurement_type: str
    unit: Optional[str]
    since: datetime
    until: datetime
    points: list[TimeSeriesPointResponse]
    total_in_range: int
    returned_count: int
    is_downsampled: bool
    aggregation_note: Optional[str]


class GapSummaryResponse(BaseModel):
    gap_count: int
    max_gap_seconds: Optional[float]
    missing_frame_like: bool


class DescriptiveStatisticsResponse(BaseModel):
    measurement_type: str
    unit: Optional[str]
    valid_count: int
    invalid_count: int
    minimum: Optional[float]
    maximum: Optional[float]
    mean: Optional[float]
    median: Optional[float]
    stdev_sample: Optional[float]
    percentiles: dict
    latest_valid_value: Optional[float]
    latest_valid_observed_at: Optional[datetime]
    rate_of_change_per_second: Optional[float]
    gap_summary: Optional[GapSummaryResponse]
    insufficient_sample: bool
    method_version: str
