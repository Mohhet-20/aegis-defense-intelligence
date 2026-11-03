"""Device-authenticated synchronization endpoints (Phase 8, Sections
5-9/12). Every route here depends on `require_device_auth`, NEVER on a
JWT/`require_permission` -- a device has no Role/Permission. See
app/api/routes/edge_devices.py for the JWT-authenticated admin side and
app/api/routes/edge_sync_admin.py for the JWT-authenticated queue view.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_device_auth
from app.db.session import get_db
from app.models.device import Device
from app.schemas.edge_sync import HealthReportAckResponse, HealthReportRequest, SyncBatchRequest, SyncBatchResponse
from app.services import edge_sync_service

router = APIRouter(prefix="/edge/sync", tags=["edge-sync"])


@router.post("/batch", response_model=SyncBatchResponse)
def submit_sync_batch(
    payload: SyncBatchRequest,
    device: Device = Depends(require_device_auth),
    db: Session = Depends(get_db),
) -> SyncBatchResponse:
    # an authenticated device can never claim to be a
    # DIFFERENT device than the one its credentials verified against --
    # the body's `device_id` is informational/self-descriptive only,
    # authorization always comes from `require_device_auth`'s result.
    if payload.device_id != device.device_identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="the batch's device_id does not match the authenticated device",
        )
    try:
        return edge_sync_service.ingest_batch(db, device, payload)
    except edge_sync_service.UnsupportedProtocolVersionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except edge_sync_service.BatchTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc


@router.post("/health", response_model=HealthReportAckResponse)
def submit_health_report(
    payload: HealthReportRequest,
    device: Device = Depends(require_device_auth),
    db: Session = Depends(get_db),
) -> HealthReportAckResponse:
    try:
        entry = edge_sync_service.process_health_report(db, device, payload)
    except edge_sync_service.UnsupportedProtocolVersionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return HealthReportAckResponse(report_id=entry.id, received_at=entry.created_at)
