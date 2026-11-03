"""Fleet sites/groups admin API. JWT-authenticated."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.fleet import FleetSiteCreateRequest, FleetSiteResponse, FleetSiteSummaryResponse
from app.services import fleet_site_service

router = APIRouter(prefix="/fleet/sites", tags=["fleet-sites"])


@router.post("", response_model=FleetSiteResponse, status_code=status.HTTP_201_CREATED)
def create_site(
    payload: FleetSiteCreateRequest,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.FLEET_SITE_MANAGE)),
    db: Session = Depends(get_db),
) -> FleetSiteResponse:
    site = fleet_site_service.create_site(db, organization_id=current_user.organization_id, actor_user_id=current_user.id, **payload.model_dump())
    return FleetSiteResponse.model_validate(site)


@router.get("", response_model=list[FleetSiteResponse])
def list_sites(
    current_user: AuthenticatedUser = Depends(require_permission(Permission.FLEET_SITE_READ)),
    db: Session = Depends(get_db),
) -> list:
    rows = db.execute(fleet_site_service.list_sites_query(current_user.organization_id)).scalars().all()
    return [FleetSiteResponse.model_validate(row) for row in rows]


@router.get("/{site_id}", response_model=FleetSiteResponse)
def get_site(
    site_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.FLEET_SITE_READ)),
    db: Session = Depends(get_db),
) -> FleetSiteResponse:
    site = fleet_site_service.get_site(db, current_user.organization_id, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet site not found")
    return FleetSiteResponse.model_validate(site)


@router.get("/{site_id}/summary", response_model=FleetSiteSummaryResponse)
def get_site_summary(
    site_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.FLEET_SITE_READ)),
    db: Session = Depends(get_db),
) -> FleetSiteSummaryResponse:
    site = fleet_site_service.get_site(db, current_user.organization_id, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet site not found")
    summary = fleet_site_service.site_summary(db, current_user.organization_id, site)
    return FleetSiteSummaryResponse(**summary)
