from __future__ import annotations

from pydantic import BaseModel


class DashboardSummaryResponse(BaseModel):
    """Every field below is a real COUNT()/aggregate query against the
    real database at response time -- never a hardcoded figure
    (Rule 3; Section 11 "do not invent metrics")."""

    total_events: int
    events_last_24h: int
    open_investigations: int
    active_sources: int
    active_sensors: int
    pending_risk_reviews: int
    ingestion_jobs_last_24h: int
    synthetic_data_present: bool
