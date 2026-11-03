from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.tenancy import require_in_org
from app.models.asset import Asset
from app.models.data_source import DataSource
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.audit import AuditRecordResponse
from app.schemas.common import Page, PageParams
from app.schemas.sensor import SensorCreateRequest, SensorLifecycleTransitionRequest, SensorResponse, SensorUpdateRequest
from app.services import audit_service, sensor_service

router = APIRouter(prefix="/sensors", tags=["sensors"])


@router.get("", response_model=Page[SensorResponse])
def list_sensors(
    category: Optional[str] = Query(default=None),
    lifecycle_status: Optional[str] = Query(default=None),
    sensor_type: Optional[str] = Query(default=None),
    measurement_type: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SENSOR_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = sensor_service.list_sensors_query(
        current_user.organization_id, category=category, lifecycle_status=lifecycle_status,
        sensor_type=sensor_type, measurement_type=measurement_type, search=search,
    )
    return paginate(db, stmt, page_params.page, page_params.page_size, SensorResponse)


@router.post("", response_model=SensorResponse, status_code=status.HTTP_201_CREATED)
def create_sensor(
    payload: SensorCreateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SENSOR_MANAGE)),
    db: Session = Depends(get_db),
) -> SensorResponse:
    # Referenced records must belong to the caller's organization (a foreign
    # id is reported exactly like a missing one).
    require_in_org(db, DataSource, current_user.organization_id, payload.source_id, "Data source")
    require_in_org(db, Asset, current_user.organization_id, payload.asset_id, "Asset")
    sensor = sensor_service.create_sensor(db, organization_id=current_user.organization_id, **payload.model_dump())
    audit_service.record(
        db, action="sensor.create", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="sensor", target_id=sensor.id, request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return SensorResponse.model_validate(sensor)


@router.get("/{sensor_id}", response_model=SensorResponse)
def get_sensor(
    sensor_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SENSOR_READ)),
    db: Session = Depends(get_db),
) -> SensorResponse:
    sensor = sensor_service.get_sensor(db, current_user.organization_id, sensor_id)
    if sensor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sensor not found")
    return SensorResponse.model_validate(sensor)


@router.patch("/{sensor_id}", response_model=SensorResponse)
def update_sensor(
    sensor_id: str,
    payload: SensorUpdateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SENSOR_MANAGE)),
    db: Session = Depends(get_db),
) -> SensorResponse:
    sensor = sensor_service.get_sensor(db, current_user.organization_id, sensor_id)
    if sensor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sensor not found")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("asset_id") is not None:
        require_in_org(db, Asset, current_user.organization_id, changes["asset_id"], "Asset")
    updated = sensor_service.update_sensor(db, sensor, **changes)
    audit_service.record(
        db, action="sensor.update", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="sensor", target_id=sensor.id, request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return SensorResponse.model_validate(updated)


@router.get("/{sensor_id}/status-history", response_model=list[AuditRecordResponse])
def get_sensor_status_history(
    sensor_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SENSOR_READ)),
    db: Session = Depends(get_db),
) -> list:
    sensor = sensor_service.get_sensor(db, current_user.organization_id, sensor_id)
    if sensor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sensor not found")
    history = sensor_service.get_status_history(db, current_user.organization_id, sensor_id)
    return [AuditRecordResponse.model_validate(record) for record in history]


@router.post("/{sensor_id}/lifecycle", response_model=SensorResponse)
def transition_sensor_lifecycle(
    sensor_id: str,
    payload: SensorLifecycleTransitionRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SENSOR_MANAGE)),
    db: Session = Depends(get_db),
) -> SensorResponse:
    sensor = sensor_service.get_sensor(db, current_user.organization_id, sensor_id)
    if sensor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sensor not found")
    try:
        updated = sensor_service.transition_lifecycle_status(db, sensor, new_status=payload.new_status, actor_user_id=current_user.id, note=payload.note)
    except sensor_service.InvalidLifecycleTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SensorResponse.model_validate(updated)


@router.post("/{sensor_id}/retire", response_model=SensorResponse)
def retire_sensor(
    sensor_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SENSOR_MANAGE)),
    db: Session = Depends(get_db),
) -> SensorResponse:
    sensor = sensor_service.get_sensor(db, current_user.organization_id, sensor_id)
    if sensor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sensor not found")
    try:
        updated = sensor_service.retire_sensor(db, sensor, actor_user_id=current_user.id)
    except sensor_service.InvalidLifecycleTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SensorResponse.model_validate(updated)
