"""Temporal exploration API: a bounded, time-filtered fetch (used for
both the Timeline Explorer's list view and historical playback) and
fixed-width time-bucket counts."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.geospatial import GeospatialQueryResponse, TimeBucketCountsResponse
from app.services import geo_timeline_service

router = APIRouter(prefix="/geospatial/timeline", tags=["geospatial-timeline"])


@router.get("", response_model=GeospatialQueryResponse)
def query_timeline(
    since: datetime = Query(...), until: datetime = Query(...),
    record_types: Optional[list[str]] = Query(default=None),
    timestamp_type: Optional[str] = Query(default=None),
    max_results: Optional[int] = Query(default=None, ge=1),
    # ascending=True is what historical playback uses -- the frontend
    # steps through the returned list IN ORDER; nothing server-side
    # holds playback state or interpolates between records (Section 8:
    # playback is real, bounded, stored data only).
    ascending: bool = Query(default=False),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_READ)),
    db: Session = Depends(get_db),
) -> GeospatialQueryResponse:
    try:
        return geo_timeline_service.query_timeline(
            db, current_user.organization_id, since=since, until=until,
            record_types=record_types, timestamp_type=timestamp_type,
            max_results=max_results, ascending=ascending,
        )
    except geo_timeline_service.TimeRangeTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/buckets", response_model=TimeBucketCountsResponse)
def get_time_bucket_counts(
    since: datetime = Query(...), until: datetime = Query(...),
    bucket_seconds: int = Query(..., gt=0),
    record_types: Optional[list[str]] = Query(default=None),
    timestamp_type: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_READ)),
    db: Session = Depends(get_db),
) -> TimeBucketCountsResponse:
    try:
        buckets, is_approximate = geo_timeline_service.time_bucket_counts(
            db, current_user.organization_id, since=since, until=until, bucket_seconds=bucket_seconds,
            record_types=record_types, timestamp_type=timestamp_type,
        )
    except geo_timeline_service.TimeRangeTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TimeBucketCountsResponse(buckets=buckets, is_approximate=is_approximate)
