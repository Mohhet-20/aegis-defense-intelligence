"""Spatial/temporal analytics API: per-record-type temporal gaps and a
fixed-size spatial grid of located-record counts (Section
9/13). Both are counts of THIS project's own stored data -- never a
causal or threat conclusion drawn from co-occurrence or density
(Section 20's prohibited-scope list)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.geospatial import SpatialGridResponse, TemporalGapsResponse
from app.services import geo_query_service, geo_timeline_service

router = APIRouter(prefix="/geospatial/analytics", tags=["geospatial-analytics"])


@router.get("/temporal-gaps", response_model=TemporalGapsResponse)
def get_temporal_gaps(
    record_type: str = Query(...),
    since: datetime = Query(...), until: datetime = Query(...),
    min_gap_seconds: float = Query(..., gt=0),
    timestamp_type: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_READ)),
    db: Session = Depends(get_db),
) -> TemporalGapsResponse:
    try:
        gaps, is_approximate = geo_timeline_service.temporal_gaps(
            db, current_user.organization_id, record_type=record_type, since=since, until=until,
            min_gap_seconds=min_gap_seconds, timestamp_type=timestamp_type,
        )
    except geo_timeline_service.TimeRangeTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TemporalGapsResponse(gaps=gaps, is_approximate=is_approximate)


@router.get("/spatial-grid", response_model=SpatialGridResponse)
def get_spatial_grid(
    record_types: Optional[list[str]] = Query(default=None),
    since: Optional[datetime] = Query(default=None), until: Optional[datetime] = Query(default=None),
    grid_resolution_degrees: Optional[float] = Query(default=None, gt=0),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_READ)),
    db: Session = Depends(get_db),
) -> SpatialGridResponse:
    try:
        cells, is_approximate = geo_query_service.spatial_grid_counts(
            db, current_user.organization_id, record_types=record_types, since=since, until=until,
            grid_resolution_degrees=grid_resolution_degrees,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SpatialGridResponse(cells=cells, is_approximate=is_approximate)
