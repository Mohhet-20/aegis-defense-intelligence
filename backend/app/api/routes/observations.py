from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.observation import ObservationResponse
from app.services import observation_service

router = APIRouter(prefix="/observations", tags=["observations"])


@router.get("", response_model=Page[ObservationResponse])
def list_observations(
    sensor_id: Optional[str] = Query(default=None),
    measurement_type: Optional[str] = Query(default=None),
    validation_status: Optional[str] = Query(default=None),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVATION_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = observation_service.list_observations_query(
        current_user.organization_id, sensor_id=sensor_id, measurement_type=measurement_type,
        validation_status=validation_status, since=since, until=until,
    )
    return paginate(db, stmt, page_params.page, page_params.page_size, ObservationResponse)


@router.get("/{observation_id}", response_model=ObservationResponse)
def get_observation(
    observation_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVATION_READ)),
    db: Session = Depends(get_db),
) -> ObservationResponse:
    observation = observation_service.get_observation(db, current_user.organization_id, observation_id)
    if observation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Observation not found")
    return ObservationResponse.model_validate(observation)
