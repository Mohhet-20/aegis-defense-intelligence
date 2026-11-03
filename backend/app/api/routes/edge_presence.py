"""Device-authenticated presence heartbeat.
Deliberately reuses `require_device_auth` and
`Device.last_seen_at` -- the exact same liveness signal
`device_service.authenticate_device()` already updates on every
device-authenticated request (a sync batch, a health report). This
endpoint exists only so a device with nothing substantive to sync can
still cheaply assert "I am alive" without constructing an empty sync
batch -- it is NOT a second, parallel tracking system.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import require_device_auth
from app.db.session import get_db
from app.models.device import Device
from app.schemas.fleet import HeartbeatRequest, HeartbeatResponse
from app.services import fleet_presence_service

router = APIRouter(prefix="/edge/presence", tags=["edge-presence"])
settings = get_settings()


@router.post("/heartbeat", response_model=HeartbeatResponse)
def submit_heartbeat(
    payload: HeartbeatRequest,
    device: Device = Depends(require_device_auth),
    db: Session = Depends(get_db),
) -> HeartbeatResponse:
    try:
        fleet_presence_service.enforce_heartbeat_rate_limit(device.id, settings=settings)
    except fleet_presence_service.HeartbeatRateLimitedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    try:
        device = fleet_presence_service.record_heartbeat(db, device, reported_at=payload.reported_at)
    except fleet_presence_service.StaleHeartbeatError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    server_now = datetime.now(timezone.utc)
    presence_state = fleet_presence_service.derive_presence_state(device.last_seen_at, settings=settings, now=server_now)
    return HeartbeatResponse(device_id=device.device_identifier, server_time=server_now, presence_state=presence_state)
