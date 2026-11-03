from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_source import DataSource
from app.models.event import Event
from app.models.ingestion_job import IngestionJob
from app.models.investigation import Investigation
from app.models.risk_assessment import RiskAssessment
from app.models.sensor import Sensor
from app.schemas.dashboard import DashboardSummaryResponse


def build_summary(db: Session, organization_id: str) -> DashboardSummaryResponse:
    """Every number here is a real aggregate query, run at response
    time, against this organization's real rows -- Rule 3."""
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    total_events = db.scalar(select(func.count()).where(Event.organization_id == organization_id)) or 0
    events_last_24h = db.scalar(
        select(func.count()).where(Event.organization_id == organization_id, Event.ingested_at >= since_24h)
    ) or 0
    open_investigations = db.scalar(
        select(func.count()).where(Investigation.organization_id == organization_id, Investigation.status.in_(["open", "active"]))
    ) or 0
    active_sources = db.scalar(
        select(func.count()).where(DataSource.organization_id == organization_id, DataSource.status == "active")
    ) or 0
    active_sensors = db.scalar(
        select(func.count()).where(Sensor.organization_id == organization_id, Sensor.status == "active")
    ) or 0
    pending_risk_reviews = db.scalar(
        select(func.count()).where(RiskAssessment.organization_id == organization_id, RiskAssessment.human_review_status == "pending")
    ) or 0
    ingestion_jobs_last_24h = db.scalar(
        select(func.count()).where(IngestionJob.organization_id == organization_id, IngestionJob.started_at >= since_24h)
    ) or 0
    synthetic_present = db.scalar(
        select(func.count()).where(Event.organization_id == organization_id, Event.data_origin == "synthetic_demo")
    ) or 0

    return DashboardSummaryResponse(
        total_events=total_events,
        events_last_24h=events_last_24h,
        open_investigations=open_investigations,
        active_sources=active_sources,
        active_sensors=active_sensors,
        pending_risk_reviews=pending_risk_reviews,
        ingestion_jobs_last_24h=ingestion_jobs_last_24h,
        synthetic_data_present=synthetic_present > 0,
    )
