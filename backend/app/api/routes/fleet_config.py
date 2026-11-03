"""Device configuration baseline admin API.
JWT-authenticated. See app/api/routes/edge_devices.py for the
per-device config/baseline-assignment/drift endpoints -- this router
only covers CREATING and LISTING baselines themselves.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.fleet import DeviceConfigBaselineCreateRequest, DeviceConfigBaselineResponse
from app.services import fleet_config_service

router = APIRouter(prefix="/fleet/config-baselines", tags=["fleet-config"])


@router.post("", response_model=DeviceConfigBaselineResponse, status_code=status.HTTP_201_CREATED)
def create_baseline(
    payload: DeviceConfigBaselineCreateRequest,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_MANAGE)),
    db: Session = Depends(get_db),
) -> DeviceConfigBaselineResponse:
    baseline = fleet_config_service.create_baseline(db, organization_id=current_user.organization_id, actor_user_id=current_user.id, **payload.model_dump())
    return DeviceConfigBaselineResponse.model_validate(baseline)


@router.get("", response_model=list[DeviceConfigBaselineResponse])
def list_baselines(
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_READ)),
    db: Session = Depends(get_db),
) -> list:
    rows = db.execute(fleet_config_service.list_baselines_query(current_user.organization_id)).scalars().all()
    return [DeviceConfigBaselineResponse.model_validate(row) for row in rows]


@router.get("/{baseline_id}", response_model=DeviceConfigBaselineResponse)
def get_baseline(
    baseline_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_READ)),
    db: Session = Depends(get_db),
) -> DeviceConfigBaselineResponse:
    baseline = fleet_config_service.get_baseline(db, current_user.organization_id, baseline_id)
    if baseline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration baseline not found")
    return DeviceConfigBaselineResponse.model_validate(baseline)
