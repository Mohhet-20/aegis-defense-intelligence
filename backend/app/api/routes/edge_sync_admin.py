"""JWT-authenticated admin view of the central sync queue (Phase 8,
Section 15) -- the Edge Operations Center's "Sync Queue" page reads
from this. See app/api/routes/edge_sync.py for the device-authenticated
submission endpoints these records are created by.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.edge_sync import SyncQueueSummaryResponse, SyncRecordResponse, SyncRecordRetryRequest
from app.services import edge_sync_service

router = APIRouter(prefix="/edge/sync", tags=["edge-sync-admin"])


def _get_record_or_404(db: Session, organization_id: str, sync_record_id: str):
    record = edge_sync_service.get_sync_record(db, organization_id, sync_record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync record not found")
    return record


@router.get("/records", response_model=Page[SyncRecordResponse])
def list_sync_records(
    device_id: Optional[str] = Query(default=None),
    sync_status: Optional[str] = Query(default=None),
    record_type: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EDGE_SYNC_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = edge_sync_service.list_sync_records_query(
        current_user.organization_id, device_id=device_id, sync_status=sync_status, record_type=record_type,
    )
    return paginate(db, stmt, page_params.page, page_params.page_size, SyncRecordResponse)


@router.get("/queue/summary", response_model=SyncQueueSummaryResponse)
def get_queue_summary(
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EDGE_SYNC_READ)),
    db: Session = Depends(get_db),
) -> SyncQueueSummaryResponse:
    return SyncQueueSummaryResponse(**edge_sync_service.get_queue_summary(db, current_user.organization_id))


@router.get("/records/{sync_record_id}", response_model=SyncRecordResponse)
def get_sync_record(
    sync_record_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EDGE_SYNC_READ)),
    db: Session = Depends(get_db),
) -> SyncRecordResponse:
    record = _get_record_or_404(db, current_user.organization_id, sync_record_id)
    return SyncRecordResponse.model_validate(record)


@router.post("/records/{sync_record_id}/retry", response_model=SyncRecordResponse)
def retry_sync_record(
    sync_record_id: str,
    payload: SyncRecordRetryRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EDGE_SYNC_MANAGE)),
    db: Session = Depends(get_db),
) -> SyncRecordResponse:
    record = _get_record_or_404(db, current_user.organization_id, sync_record_id)
    try:
        record = edge_sync_service.force_retry_sync_record(db, record, actor_user_id=current_user.id)
    except edge_sync_service.InvalidSyncTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SyncRecordResponse.model_validate(record)


@router.post("/records/{sync_record_id}/cancel", response_model=SyncRecordResponse)
def cancel_sync_record(
    sync_record_id: str,
    payload: SyncRecordRetryRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EDGE_SYNC_MANAGE)),
    db: Session = Depends(get_db),
) -> SyncRecordResponse:
    record = _get_record_or_404(db, current_user.organization_id, sync_record_id)
    try:
        record = edge_sync_service.cancel_sync_record(db, record, actor_user_id=current_user.id, reason=payload.reason)
    except edge_sync_service.InvalidSyncTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SyncRecordResponse.model_validate(record)


@router.post("/recover-stale", status_code=status.HTTP_200_OK)
def recover_stale_syncing_records(
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EDGE_SYNC_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    """Manually triggers the crash-recovery sweep for this
    organization. This project has no background job scheduler (every
    phase so far is request/response only -- see
    docs/operations/EDGE_TROUBLESHOOTING.md), so an operator (or a
    scheduled external call to this endpoint) is how the sweep actually
    runs in this deployment; it is NOT run automatically on a timer."""
    recovered = edge_sync_service.recover_stale_syncing_records(db, organization_id=current_user.organization_id)
    return {"recovered_count": recovered}
