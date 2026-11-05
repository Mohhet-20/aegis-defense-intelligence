"""Fusion pipeline orchestration. Composes
the `correlation_service.recompute()` (temporal/spatial/
identifier candidate generation, steps 1-8 and 10 of Section 4's
sequence) with this layer's `conflict_service.detect_conflicts()`
(step 8's contradiction-detection half), and records the whole run as
one inspectable `FusionJob` row (step 12: "update derived analytical
summaries without modifying original source observations" -- a
FusionJob never touches an Event row, only counts them).

This is the ONE explicit, authorized entry point that runs the fusion
pipeline -- same discipline as the `recompute()`: there is no
background job, a run only happens because someone with
`FUSION_MANAGE` asked for one.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.fusion_job import FusionJob
from app.services import conflict_service, correlation_service

settings = get_settings()

FUSION_RULE_VERSION = "1.0"


def run_fusion_job(
    db: Session,
    organization_id: str,
    *,
    triggered_by_user_id: Optional[str],
    time_window_seconds: Optional[int] = None,
    spatial_threshold_meters: Optional[float] = None,
    spatial_conflict_threshold_meters: Optional[float] = None,
) -> FusionJob:
    window = time_window_seconds if time_window_seconds is not None else settings.FUSION_TIME_WINDOW_SECONDS_DEFAULT
    spatial_threshold = spatial_threshold_meters if spatial_threshold_meters is not None else settings.FUSION_SPATIAL_THRESHOLD_METERS_DEFAULT

    job = FusionJob(
        organization_id=organization_id,
        status="running",
        triggered_by_user_id=triggered_by_user_id,
        rule_version=FUSION_RULE_VERSION,
        parameters={
            "time_window_seconds": window,
            "spatial_threshold_meters": spatial_threshold,
            "spatial_conflict_threshold_meters": spatial_conflict_threshold_meters or settings.FUSION_SPATIAL_CONFLICT_THRESHOLD_METERS,
        },
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        correlation_result = correlation_service.recompute(
            db, organization_id,
            time_window_seconds=window,
            spatial_threshold_meters=spatial_threshold,
            max_events=settings.FUSION_MAX_EVENTS_PER_RUN,
            time_window_seconds_by_type=settings.fusion_time_window_seconds_by_type or None,
        )
        conflict_result = conflict_service.detect_conflicts(
            db, organization_id,
            correlation_batch_id=correlation_result["batch_id"],
            spatial_conflict_threshold_meters=spatial_conflict_threshold_meters,
        )
        job.status = "completed"
        job.events_considered = correlation_result["events_considered"]
        job.correlations_created = correlation_result["correlations_created"]
        job.conflicts_created = conflict_result["conflicts_created"]
        job.finished_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001 -- a fusion run failing is a real, reportable outcome, never a silent swallow
        db.rollback()
        job = db.merge(job)
        job.status = "failed"
        job.error_message = str(exc)[:2000]
        job.finished_at = datetime.now(timezone.utc)

    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, organization_id: str, job_id: str) -> Optional[FusionJob]:
    stmt = select(FusionJob).where(FusionJob.id == job_id, FusionJob.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_jobs_query(organization_id: str):
    return select(FusionJob).where(FusionJob.organization_id == organization_id).order_by(FusionJob.started_at.desc())
