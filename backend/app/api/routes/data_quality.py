from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.quality import DataQualitySummaryResponse, JobsSummaryResponse
from app.services import quality_service

router = APIRouter(prefix="/data-quality", tags=["data-quality"])


@router.get("/summary", response_model=DataQualitySummaryResponse)
def get_data_quality_summary(
    source_id: Optional[str] = Query(default=None),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DATA_QUALITY_READ)),
    db: Session = Depends(get_db),
) -> DataQualitySummaryResponse:
    """Always states its own denominator (`total`) and time window --
    never a single unlabeled score."""
    summary = quality_service.summarize_data_quality(db, current_user.organization_id, source_id=source_id, since=since, until=until)
    return DataQualitySummaryResponse(**summary)


@router.get("/jobs-summary", response_model=JobsSummaryResponse)
def get_jobs_summary(
    source_id: Optional[str] = Query(default=None),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DATA_QUALITY_READ)),
    db: Session = Depends(get_db),
) -> JobsSummaryResponse:
    summary = quality_service.summarize_jobs(db, current_user.organization_id, source_id=source_id, since=since, until=until)
    return JobsSummaryResponse(**summary)
