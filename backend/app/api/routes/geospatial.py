"""Core geospatial API: overview, viewport/radius spatial queries,
location-quality reporting, and spatial-relationship candidate
generation/listing. Every endpoint is
tenant-scoped through `current_user.organization_id` -- never a raw
request-supplied organization id -- and every bounded-result service
function is called with the service's own defaults/caps, never
bypassed here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.geospatial import (
    GeospatialOverviewResponse,
    GeospatialQueryResponse,
    LocationQualityRecordResponse,
    LocationQualitySummaryResponse,
    SpatialRelationshipCandidateResponse,
    SpatialRelationshipGenerateRequest,
    SpatialRelationshipRunResponse,
)
from app.services import audit_service, geo_overview_service, geo_query_service, location_quality_service, spatial_relationship_service

router = APIRouter(prefix="/geospatial", tags=["geospatial"])


@router.get("/overview", response_model=GeospatialOverviewResponse)
def get_overview(
    record_types: Optional[list[str]] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_READ)),
    db: Session = Depends(get_db),
) -> GeospatialOverviewResponse:
    return geo_overview_service.build_overview(db, current_user.organization_id, record_types=record_types)


@router.get("/viewport", response_model=GeospatialQueryResponse)
def query_viewport(
    min_lat: float = Query(...), max_lat: float = Query(...),
    min_lon: float = Query(...), max_lon: float = Query(...),
    record_types: Optional[list[str]] = Query(default=None),
    since: Optional[datetime] = Query(default=None), until: Optional[datetime] = Query(default=None),
    timestamp_type: Optional[str] = Query(default=None),
    max_results: Optional[int] = Query(default=None, ge=1),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_READ)),
    db: Session = Depends(get_db),
) -> GeospatialQueryResponse:
    try:
        return geo_query_service.query_viewport(
            db, current_user.organization_id,
            min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon,
            record_types=record_types, since=since, until=until,
            timestamp_type=timestamp_type, max_results=max_results,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/radius", response_model=GeospatialQueryResponse)
def query_radius(
    center_latitude: float = Query(...), center_longitude: float = Query(...), radius_km: float = Query(...),
    record_types: Optional[list[str]] = Query(default=None),
    since: Optional[datetime] = Query(default=None), until: Optional[datetime] = Query(default=None),
    timestamp_type: Optional[str] = Query(default=None),
    max_results: Optional[int] = Query(default=None, ge=1),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_READ)),
    db: Session = Depends(get_db),
) -> GeospatialQueryResponse:
    try:
        return geo_query_service.query_radius(
            db, current_user.organization_id,
            center_latitude=center_latitude, center_longitude=center_longitude, radius_km=radius_km,
            record_types=record_types, since=since, until=until,
            timestamp_type=timestamp_type, max_results=max_results,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/quality/summary", response_model=LocationQualitySummaryResponse)
def get_quality_summary(
    record_types: Optional[list[str]] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_READ)),
    db: Session = Depends(get_db),
) -> LocationQualitySummaryResponse:
    return location_quality_service.quality_summary(db, current_user.organization_id, record_types=record_types)


@router.get("/quality/issues", response_model=list[LocationQualityRecordResponse])
def list_quality_issues(
    record_types: Optional[list[str]] = Query(default=None),
    only_issues: bool = Query(default=True),
    limit: int = Query(default=200, ge=1, le=1000),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_READ)),
    db: Session = Depends(get_db),
) -> list[LocationQualityRecordResponse]:
    return location_quality_service.list_quality_issues(
        db, current_user.organization_id, record_types=record_types, only_issues=only_issues, limit=limit,
    )


@router.post("/relationships/generate", response_model=SpatialRelationshipRunResponse)
def generate_spatial_relationships(
    payload: SpatialRelationshipGenerateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_MANAGE)),
    db: Session = Depends(get_db),
) -> SpatialRelationshipRunResponse:
    try:
        result = spatial_relationship_service.generate_candidates(
            db, current_user.organization_id,
            since=payload.since, until=payload.until,
            distance_threshold_m=payload.distance_threshold_m, time_window_seconds=payload.time_window_seconds,
            created_by_user_id=current_user.id,
        )
        audit_service.record(
            db, action="geospatial.relationships_generate", actor_user_id=current_user.id, organization_id=current_user.organization_id,
            request_id=getattr(request.state, "request_id", None),
            context_metadata={"distance_threshold_m": payload.distance_threshold_m, "time_window_seconds": payload.time_window_seconds},
        )
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/relationships", response_model=list[SpatialRelationshipCandidateResponse])
def list_spatial_relationships(
    review_status: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    # Reviewing a candidate (confirm/reject/uncertain) is NOT done here
    # -- see POST /relationships/{relationship_id}/review, which this
    # endpoint's results point back to via `relationship_id`.
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_READ)),
    db: Session = Depends(get_db),
) -> list[SpatialRelationshipCandidateResponse]:
    return spatial_relationship_service.list_candidates(db, current_user.organization_id, review_status=review_status, limit=limit)
