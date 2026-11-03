from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DataQualitySummaryResponse(BaseModel):
    total: int
    valid: int
    invalid: int
    duplicate: int
    accepted: Optional[int] = None
    acceptance_rate: Optional[float]
    rejection_rate: Optional[float]
    duplicate_rate: Optional[float]
    rejection_categories: dict[str, int]
    warning_categories: dict[str, int]
    source_id: Optional[str]
    since: Optional[datetime]
    until: Optional[datetime]


class JobsSummaryResponse(BaseModel):
    total_jobs: int
    by_status: dict[str, int]
    accepted_total: int
    rejected_total: int
    duplicate_total: int
    source_id: Optional[str]
    since: Optional[datetime]
    until: Optional[datetime]
