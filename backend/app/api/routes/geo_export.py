"""Bounded GeoJSON/CSV export API. Gated by
GEOSPATIAL_EXPORT specifically -- not GEOSPATIAL_READ -- mirroring
Phase 2's existing DATA_EXPORT split: being able to view the map is
not the same permission as being able to bulk-export its data."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.services import audit_service, geo_export_service

router = APIRouter(prefix="/geospatial/export", tags=["geospatial-export"])


def _run_export(
    exporter, db: Session, current_user: AuthenticatedUser, request: Request, *,
    record_types: Optional[list[str]], min_lat, max_lat, min_lon, max_lon,
    since: Optional[datetime], until: Optional[datetime], max_features: Optional[int],
) -> Response:
    try:
        result = exporter(
            db, current_user.organization_id, record_types=record_types,
            min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon,
            since=since, until=until, max_features=max_features,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_service.record(
        db, action="geospatial.export", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="geospatial_export", target_id=result.format, request_id=getattr(request.state, "request_id", None),
        context_metadata={"format": result.format, "feature_count": result.feature_count, "truncated": result.truncated, "filters": result.filters_applied},
    )
    db.commit()
    return Response(
        content=result.content, media_type=result.content_type,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )


@router.get("/geojson")
def export_geojson(
    request: Request,
    record_types: list[str] = Query(...),
    min_lat: Optional[float] = Query(default=None), max_lat: Optional[float] = Query(default=None),
    min_lon: Optional[float] = Query(default=None), max_lon: Optional[float] = Query(default=None),
    since: Optional[datetime] = Query(default=None), until: Optional[datetime] = Query(default=None),
    max_features: Optional[int] = Query(default=None, ge=1),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_EXPORT)),
    db: Session = Depends(get_db),
) -> Response:
    return _run_export(
        geo_export_service.export_geojson, db, current_user, request,
        record_types=record_types, min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon,
        since=since, until=until, max_features=max_features,
    )


@router.get("/csv")
def export_csv(
    request: Request,
    record_types: list[str] = Query(...),
    min_lat: Optional[float] = Query(default=None), max_lat: Optional[float] = Query(default=None),
    min_lon: Optional[float] = Query(default=None), max_lon: Optional[float] = Query(default=None),
    since: Optional[datetime] = Query(default=None), until: Optional[datetime] = Query(default=None),
    max_features: Optional[int] = Query(default=None, ge=1),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GEOSPATIAL_EXPORT)),
    db: Session = Depends(get_db),
) -> Response:
    return _run_export(
        geo_export_service.export_csv, db, current_user, request,
        record_types=record_types, min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon,
        since=since, until=until, max_features=max_features,
    )
