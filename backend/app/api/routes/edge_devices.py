"""Device registry + lifecycle admin API --
JWT-authenticated (human analysts/administrators), distinct from
app/api/routes/edge_sync.py's device-authenticated endpoints below."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.device import (
    DeviceHealthReportResponse,
    DeviceLifecycleActionRequest,
    DeviceRegisterRequest,
    DeviceRegistrationResult,
    DeviceResponse,
    DeviceSiteAssignRequest,
)
from app.schemas.fleet import (
    DeviceCapabilityResponse,
    DeviceConfigAssignBaselineRequest,
    DeviceConfigDriftResponse,
    DeviceConfigStateResponse,
    DeviceConfigUpdateRequest,
)
from app.services import audit_service, device_service, fleet_site_service

router = APIRouter(prefix="/devices", tags=["edge-devices"])
settings = get_settings()


def _get_device_or_404(db: Session, organization_id: str, device_id: str):
    device = device_service.get_device(db, organization_id, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


@router.post("", response_model=DeviceRegistrationResult, status_code=status.HTTP_201_CREATED)
def register_device(
    payload: DeviceRegisterRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_MANAGE)),
    db: Session = Depends(get_db),
) -> DeviceRegistrationResult:
    if payload.site_id is not None and fleet_site_service.get_site(db, current_user.organization_id, payload.site_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    try:
        device, api_key = device_service.register_device(
            db, organization_id=current_user.organization_id, actor_user_id=current_user.id, **payload.model_dump()
        )
    except device_service.DuplicateDeviceIdentifierError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return DeviceRegistrationResult(device=device_service.to_response(db, device), api_key=api_key)


@router.get("", response_model=Page[DeviceResponse])
def list_devices(
    administrative_status: Optional[str] = Query(default=None),
    connectivity_state: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = device_service.list_devices_query(
        current_user.organization_id, administrative_status=administrative_status, connectivity_state=connectivity_state, search=search,
    )
    page = max(page_params.page, 1)
    page_size = max(1, min(page_params.page_size, settings.MAX_PAGE_SIZE))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).scalars().all()
    items = [device_service.to_response(db, row) for row in rows]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{device_id}", response_model=DeviceResponse)
def get_device(
    device_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_READ)),
    db: Session = Depends(get_db),
) -> DeviceResponse:
    device = _get_device_or_404(db, current_user.organization_id, device_id)
    return device_service.to_response(db, device)


@router.post("/{device_id}/activate", response_model=DeviceResponse)
def activate_device(
    device_id: str,
    payload: DeviceLifecycleActionRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_MANAGE)),
    db: Session = Depends(get_db),
) -> DeviceResponse:
    device = _get_device_or_404(db, current_user.organization_id, device_id)
    try:
        device = device_service.activate_device(db, device, actor_user_id=current_user.id, reason=payload.reason)
    except device_service.InvalidDeviceLifecycleTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return device_service.to_response(db, device)


@router.post("/{device_id}/suspend", response_model=DeviceResponse)
def suspend_device(
    device_id: str,
    payload: DeviceLifecycleActionRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_MANAGE)),
    db: Session = Depends(get_db),
) -> DeviceResponse:
    device = _get_device_or_404(db, current_user.organization_id, device_id)
    try:
        device = device_service.suspend_device(db, device, actor_user_id=current_user.id, reason=payload.reason)
    except device_service.InvalidDeviceLifecycleTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return device_service.to_response(db, device)


@router.post("/{device_id}/revoke", response_model=DeviceResponse)
def revoke_device(
    device_id: str,
    payload: DeviceLifecycleActionRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_MANAGE)),
    db: Session = Depends(get_db),
) -> DeviceResponse:
    device = _get_device_or_404(db, current_user.organization_id, device_id)
    try:
        device = device_service.revoke_device(db, device, actor_user_id=current_user.id, reason=payload.reason)
    except device_service.InvalidDeviceLifecycleTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return device_service.to_response(db, device)


@router.post("/{device_id}/maintenance", response_model=DeviceResponse)
def enter_device_maintenance(
    device_id: str,
    payload: DeviceLifecycleActionRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_MANAGE)),
    db: Session = Depends(get_db),
) -> DeviceResponse:
    """ -- a temporary, explicit, reversible
    administrative pause, distinct from the `suspend` (a
    security-suspicion pause)."""
    device = _get_device_or_404(db, current_user.organization_id, device_id)
    try:
        device = device_service.enter_maintenance(db, device, actor_user_id=current_user.id, reason=payload.reason)
    except device_service.InvalidDeviceLifecycleTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return device_service.to_response(db, device)


@router.post("/{device_id}/decommission", response_model=DeviceResponse)
def decommission_device(
    device_id: str,
    payload: DeviceLifecycleActionRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_MANAGE)),
    db: Session = Depends(get_db),
) -> DeviceResponse:
    """ -- permanent end-of-life, distinct from
    the `revoke` (a security response). Never deletes historical
    sync/health/audit rows."""
    device = _get_device_or_404(db, current_user.organization_id, device_id)
    try:
        device = device_service.decommission_device(db, device, actor_user_id=current_user.id, reason=payload.reason)
    except device_service.InvalidDeviceLifecycleTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return device_service.to_response(db, device)


@router.get("/{device_id}/lifecycle-preview")
def preview_device_lifecycle_transition(
    device_id: str,
    target_status: str = Query(...),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_READ)),
    db: Session = Depends(get_db),
) -> dict:
    """"confirmation previews for consequential
    actions" -- read-only, makes no change. The Fleet Operations Center
    calls this before showing a confirm dialog for any consequential
    lifecycle action."""
    device = _get_device_or_404(db, current_user.organization_id, device_id)
    return device_service.preview_lifecycle_transition(db, device, new_status=target_status)


@router.post("/{device_id}/site", response_model=DeviceResponse)
def assign_device_site(
    device_id: str,
    payload: DeviceSiteAssignRequest,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_MANAGE)),
    db: Session = Depends(get_db),
) -> DeviceResponse:
    device = _get_device_or_404(db, current_user.organization_id, device_id)
    site = None
    if payload.site_id is not None:
        from app.services import fleet_site_service

        site = fleet_site_service.get_site(db, current_user.organization_id, payload.site_id)
        if site is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet site not found")
    from app.services import fleet_site_service

    device = fleet_site_service.assign_device_to_site(db, device, site, actor_user_id=current_user.id)
    return device_service.to_response(db, device)


@router.post("/{device_id}/rotate-key", response_model=DeviceRegistrationResult)
def rotate_device_key(
    device_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_MANAGE)),
    db: Session = Depends(get_db),
) -> DeviceRegistrationResult:
    device = _get_device_or_404(db, current_user.organization_id, device_id)
    try:
        device, api_key = device_service.rotate_api_key(db, device, actor_user_id=current_user.id)
    except device_service.InvalidDeviceLifecycleTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DeviceRegistrationResult(device=device_service.to_response(db, device), api_key=api_key)


@router.get("/{device_id}/health-reports", response_model=Page[DeviceHealthReportResponse])
def list_device_health_reports(
    device_id: str,
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_READ)),
    db: Session = Depends(get_db),
) -> Page:
    _get_device_or_404(db, current_user.organization_id, device_id)
    from app.api.pagination import paginate

    stmt = device_service.get_health_reports_query(current_user.organization_id, device_id)
    page_size = min(page_params.page_size, settings.EDGE_DEVICE_HEALTH_REPORT_MAX_RESULTS)
    return paginate(db, stmt, page_params.page, page_size, DeviceHealthReportResponse)


@router.get("/{device_id}/capabilities", response_model=list[DeviceCapabilityResponse])
def list_device_capabilities(
    device_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_READ)),
    db: Session = Depends(get_db),
) -> list:
    _get_device_or_404(db, current_user.organization_id, device_id)
    from app.services import fleet_capability_service

    rows = fleet_capability_service.list_for_device(db, current_user.organization_id, device_id)
    return [DeviceCapabilityResponse.model_validate(row) for row in rows]


@router.get("/{device_id}/config", response_model=DeviceConfigStateResponse)
def get_device_config(
    device_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_READ)),
    db: Session = Depends(get_db),
) -> DeviceConfigStateResponse:
    device = _get_device_or_404(db, current_user.organization_id, device_id)
    from app.services import fleet_config_service

    drift = fleet_config_service.compute_drift(db, device)
    return DeviceConfigStateResponse(
        current_config=device.current_config, config_revision=device.config_revision,
        config_baseline_id=device.config_baseline_id, drift=DeviceConfigDriftResponse(**drift),
    )


@router.put("/{device_id}/config", response_model=DeviceConfigStateResponse)
def update_device_config(
    device_id: str,
    payload: DeviceConfigUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_MANAGE)),
    db: Session = Depends(get_db),
) -> DeviceConfigStateResponse:
    device = _get_device_or_404(db, current_user.organization_id, device_id)
    from app.services import fleet_config_service

    try:
        device = fleet_config_service.update_config(
            db, device, new_config=payload.new_config, expected_revision=payload.expected_revision, actor_user_id=current_user.id,
        )
    except fleet_config_service.ConfigRevisionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    drift = fleet_config_service.compute_drift(db, device)
    return DeviceConfigStateResponse(
        current_config=device.current_config, config_revision=device.config_revision,
        config_baseline_id=device.config_baseline_id, drift=DeviceConfigDriftResponse(**drift),
    )


@router.post("/{device_id}/config/baseline", response_model=DeviceConfigStateResponse)
def assign_device_baseline(
    device_id: str,
    payload: DeviceConfigAssignBaselineRequest,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_MANAGE)),
    db: Session = Depends(get_db),
) -> DeviceConfigStateResponse:
    device = _get_device_or_404(db, current_user.organization_id, device_id)
    from app.services import fleet_config_service

    baseline = fleet_config_service.get_baseline(db, current_user.organization_id, payload.baseline_id)
    if baseline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration baseline not found")
    device = fleet_config_service.assign_baseline(db, device, baseline, actor_user_id=current_user.id)
    drift = fleet_config_service.compute_drift(db, device)
    return DeviceConfigStateResponse(
        current_config=device.current_config, config_revision=device.config_revision,
        config_baseline_id=device.config_baseline_id, drift=DeviceConfigDriftResponse(**drift),
    )


@router.get("/{device_id}/status-history")
def get_device_status_history(
    device_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DEVICE_READ)),
    db: Session = Depends(get_db),
) -> list:
    _get_device_or_404(db, current_user.organization_id, device_id)
    from app.schemas.audit import AuditRecordResponse

    history = audit_service.list_for_target(db, current_user.organization_id, target_type="device", target_id=device_id)
    return [AuditRecordResponse.model_validate(record) for record in history]
