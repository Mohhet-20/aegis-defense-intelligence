"""Infrastructure alert center admin API.
JWT-authenticated. See app/models/infrastructure_alert.py and
app/services/fleet_alert_service.py.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.models.infrastructure_alert import InfrastructureAlert
from app.schemas.common import Page, PageParams
from app.schemas.fleet import AlertActionRequest, InfrastructureAlertResponse
from app.services import fleet_alert_service

router = APIRouter(prefix="/fleet/alerts", tags=["infra-alerts"])
settings = get_settings()


def _get_alert_or_404(db: Session, organization_id: str, alert_id: str) -> InfrastructureAlert:
    alert = fleet_alert_service.get_alert(db, organization_id, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Infrastructure alert not found")
    return alert


@router.post("/evaluate-sweep", status_code=status.HTTP_200_OK)
def evaluate_alerts_sweep(
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INFRA_ALERT_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    """Manually triggers presence/health/drift re-evaluation across
    every device in this organization. Mirrors
    `POST /edge/sync/recover-stale`'s exact pattern: this
    project has no in-process background scheduler, so this is how
    `device_offline`/`device_stale` alerts actually get raised in
    practice -- a device that has gone silent makes no request of its
    own, so nothing re-evaluates it until an operator (or a scheduled
    external call to this endpoint) runs this sweep. See
    app/services/fleet_alert_service.py's module docstring for the full
    "why this sweep exists" rationale."""
    result = fleet_alert_service.evaluate_alerts_for_all_devices(db, organization_id=current_user.organization_id)
    return result


@router.get("", response_model=Page[InfrastructureAlertResponse])
def list_alerts(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    severity: Optional[str] = Query(default=None),
    device_id: Optional[str] = Query(default=None),
    alert_type: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INFRA_ALERT_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = fleet_alert_service.list_alerts_query(current_user.organization_id, status=status_filter, severity=severity, device_id=device_id, alert_type=alert_type)
    page = max(page_params.page, 1)
    page_size = max(1, min(page_params.page_size, settings.FLEET_ALERT_MAX_PAGE_SIZE))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).scalars().all()
    items = [InfrastructureAlertResponse.model_validate(row) for row in rows]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{alert_id}", response_model=InfrastructureAlertResponse)
def get_alert(
    alert_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INFRA_ALERT_READ)),
    db: Session = Depends(get_db),
) -> InfrastructureAlertResponse:
    alert = _get_alert_or_404(db, current_user.organization_id, alert_id)
    return InfrastructureAlertResponse.model_validate(alert)


@router.post("/{alert_id}/acknowledge", response_model=InfrastructureAlertResponse)
def acknowledge_alert(
    alert_id: str,
    payload: AlertActionRequest,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INFRA_ALERT_MANAGE)),
    db: Session = Depends(get_db),
) -> InfrastructureAlertResponse:
    alert = _get_alert_or_404(db, current_user.organization_id, alert_id)
    try:
        alert = fleet_alert_service.acknowledge_alert(db, alert, actor_user_id=current_user.id, note=payload.note)
    except fleet_alert_service.InvalidAlertTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return InfrastructureAlertResponse.model_validate(alert)


@router.post("/{alert_id}/resolve", response_model=InfrastructureAlertResponse)
def resolve_alert(
    alert_id: str,
    payload: AlertActionRequest,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INFRA_ALERT_MANAGE)),
    db: Session = Depends(get_db),
) -> InfrastructureAlertResponse:
    alert = _get_alert_or_404(db, current_user.organization_id, alert_id)
    try:
        alert = fleet_alert_service.resolve_alert(db, alert, actor_user_id=current_user.id, note=payload.note)
    except fleet_alert_service.InvalidAlertTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return InfrastructureAlertResponse.model_validate(alert)


@router.post("/{alert_id}/reopen", response_model=InfrastructureAlertResponse)
def reopen_alert(
    alert_id: str,
    payload: AlertActionRequest,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.INFRA_ALERT_MANAGE)),
    db: Session = Depends(get_db),
) -> InfrastructureAlertResponse:
    alert = _get_alert_or_404(db, current_user.organization_id, alert_id)
    try:
        alert = fleet_alert_service.reopen_alert(db, alert, actor_user_id=current_user.id, note=payload.note)
    except fleet_alert_service.InvalidAlertTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return InfrastructureAlertResponse.model_validate(alert)
