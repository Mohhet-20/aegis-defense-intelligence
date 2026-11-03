"""Fleet overview/analytics API. JWT-authenticated.
See app/services/fleet_analytics_service.py for the exact
numerator/denominator/time-window definition of every figure."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.fleet import FleetOverviewResponse
from app.services import fleet_analytics_service

router = APIRouter(prefix="/fleet/analytics", tags=["fleet-analytics"])


@router.get("/overview", response_model=FleetOverviewResponse)
def get_fleet_overview(
    current_user: AuthenticatedUser = Depends(require_permission(Permission.FLEET_ANALYTICS_READ)),
    db: Session = Depends(get_db),
) -> FleetOverviewResponse:
    overview = fleet_analytics_service.fleet_overview(db, current_user.organization_id)
    return FleetOverviewResponse(**overview)
