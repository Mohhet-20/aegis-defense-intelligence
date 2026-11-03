from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.lifecycle import LifecycleRequestCreate, LifecycleRequestResponse, LifecycleReviewBody
from app.services import lifecycle_service as svc

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


def _rid(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


def _raise(exc: svc.LifecycleError):
    detail = {"detail": str(exc), "blockers": exc.blockers} if getattr(exc, "blockers", None) else str(exc)
    raise HTTPException(status_code=exc.status_code, detail=detail) from exc


@router.get("/policies")
def get_policies(current_user: AuthenticatedUser = Depends(require_permission(Permission.LIFECYCLE_READ))) -> dict:
    return svc.policies()


@router.get("/preview")
def preview(
    resource_type: str = Query(max_length=40),
    older_than_days: Optional[int] = Query(default=None, ge=1, le=36500),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.LIFECYCLE_READ)),
    db: Session = Depends(get_db),
) -> dict:
    """Dry run: lists records that WOULD be eligible, with blockers. Changes nothing."""
    try:
        return svc.preview(db, current_user.organization_id, resource_type, older_than_days=older_than_days)
    except svc.LifecycleError as exc:
        _raise(exc)


@router.get("/audit-retention")
def audit_retention(current_user: AuthenticatedUser = Depends(require_permission(Permission.LIFECYCLE_READ)), db: Session = Depends(get_db)) -> dict:
    return svc.audit_retention_report(db, current_user.organization_id)


@router.get("/requests", response_model=Page[LifecycleRequestResponse])
def list_requests(
    status_filter: Optional[str] = Query(default=None, alias="status", max_length=20),
    resource_type: Optional[str] = Query(default=None, max_length=40),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.LIFECYCLE_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = svc.list_requests_query(current_user.organization_id, status=status_filter, resource_type=resource_type)
    return paginate(db, stmt, page_params.page, page_params.page_size, LifecycleRequestResponse)


@router.get("/requests/{lifecycle_request_id}", response_model=LifecycleRequestResponse)
def get_request(
    lifecycle_request_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.LIFECYCLE_READ)),
    db: Session = Depends(get_db),
) -> LifecycleRequestResponse:
    try:
        return LifecycleRequestResponse.model_validate(svc.get_request(db, current_user.organization_id, lifecycle_request_id))
    except svc.LifecycleError as exc:
        _raise(exc)


@router.post("/requests", response_model=LifecycleRequestResponse, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: LifecycleRequestCreate,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.LIFECYCLE_REQUEST)),
    db: Session = Depends(get_db),
) -> LifecycleRequestResponse:
    try:
        req = svc.create_request(db, current_user, resource_type=payload.resource_type, resource_id=payload.resource_id,
                                 action=payload.action, reason=payload.reason, request_id=_rid(request))
        db.commit()
        return LifecycleRequestResponse.model_validate(req)
    except svc.LifecycleError as exc:
        db.rollback()
        _raise(exc)


def _review(lifecycle_request_id: str, body: LifecycleReviewBody, request: Request, user: AuthenticatedUser, db: Session, approve: bool):
    try:
        req = svc.get_request(db, user.organization_id, lifecycle_request_id)
        req = svc.review(db, user, req, approve=approve, note=body.note, request_id=_rid(request))
        db.commit()
        return LifecycleRequestResponse.model_validate(req)
    except svc.LifecycleError as exc:
        db.rollback()
        _raise(exc)


@router.post("/requests/{lifecycle_request_id}/approve", response_model=LifecycleRequestResponse)
def approve(lifecycle_request_id: str, request: Request, body: LifecycleReviewBody = LifecycleReviewBody(),
            current_user: AuthenticatedUser = Depends(require_permission(Permission.LIFECYCLE_APPROVE)), db: Session = Depends(get_db)):
    return _review(lifecycle_request_id, body, request, current_user, db, True)


@router.post("/requests/{lifecycle_request_id}/reject", response_model=LifecycleRequestResponse)
def reject(lifecycle_request_id: str, request: Request, body: LifecycleReviewBody = LifecycleReviewBody(),
           current_user: AuthenticatedUser = Depends(require_permission(Permission.LIFECYCLE_APPROVE)), db: Session = Depends(get_db)):
    return _review(lifecycle_request_id, body, request, current_user, db, False)


@router.post("/requests/{lifecycle_request_id}/cancel", response_model=LifecycleRequestResponse)
def cancel(lifecycle_request_id: str, request: Request,
           current_user: AuthenticatedUser = Depends(require_permission(Permission.LIFECYCLE_REQUEST)), db: Session = Depends(get_db)):
    try:
        req = svc.get_request(db, current_user.organization_id, lifecycle_request_id)
        req = svc.cancel(db, current_user, req, request_id=_rid(request))
        db.commit()
        return LifecycleRequestResponse.model_validate(req)
    except svc.LifecycleError as exc:
        db.rollback()
        _raise(exc)


@router.post("/requests/{lifecycle_request_id}/execute", response_model=LifecycleRequestResponse)
def execute(lifecycle_request_id: str, request: Request,
            current_user: AuthenticatedUser = Depends(require_permission(Permission.LIFECYCLE_APPROVE)), db: Session = Depends(get_db)):
    """Executes an approved request. The response status is the truth:
    `executed` = fully done; `cleanup_pending` = database change committed
    but the stored file could not be removed (re-POST to retry); `failed` =
    nothing was changed. HTTP 200 does NOT by itself mean success."""
    try:
        req = svc.get_request(db, current_user.organization_id, lifecycle_request_id)
        return LifecycleRequestResponse.model_validate(svc.execute(db, current_user, req, request_id=_rid(request)))
    except svc.LifecycleError as exc:
        db.rollback()
        _raise(exc)
