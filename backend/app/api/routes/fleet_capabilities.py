"""Fleet-wide capability discovery API.
JWT-authenticated. See app/api/routes/edge_devices.py for the
per-device capability list endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.fleet import FleetCapabilitySummaryEntry
from app.services import fleet_capability_service

router = APIRouter(prefix="/fleet/capabilities", tags=["fleet-capabilities"])
settings = get_settings()


@router.get("/summary", response_model=list[FleetCapabilitySummaryEntry])
def get_fleet_capability_summary(
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_READ)),
    db: Session = Depends(get_db),
) -> list:
    return fleet_capability_service.fleet_capability_summary(db, current_user.organization_id, settings=settings)
