"""Capability discovery. See
app/models/device_capability.py for the five-state rationale.

Ingestion sources (deliberately reusing the existing data, never
a new parallel reporting channel -- Part 3's "reuse" instruction
applies here too):
  - `Device.capabilities` (self-reported at registration/
    update) is this device's declared SUPPORTED set.
  - `HealthReportRequest.runtime_capabilities` (the existing
    health-report field, a list of capability keys the device
    considers currently installed and ready to run) drives INSTALLED
    and AVAILABLE_AND_READY.
  - `HealthReportRequest.model_status` (the existing free-form
    health-report field, shaped `{capability_key: {"healthy": bool}}`)
    drives HEALTHY and LAST_VERIFIED_AT -- computed by the server from
    the device's own accumulated health-report history, not re-derived
    from a single standalone claim.

A capability_key mentioned in an older report but absent from the
latest one is NOT silently flipped to False -- "recently verified" is
exactly the signal that distinguishes a capability nobody has reported
in a while from one actively confirmed working right now; see
`last_verified_at`/`last_reported_at` on the model.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.device import Device
from app.models.device_capability import DeviceCapability
from app.models.device_health_report import DeviceHealthReport
from app.services.timeutil import ensure_utc


def _get_or_create(db: Session, device: Device, capability_key: str) -> DeviceCapability:
    stmt = select(DeviceCapability).where(DeviceCapability.device_id == device.id, DeviceCapability.capability_key == capability_key)
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        row = DeviceCapability(organization_id=device.organization_id, device_id=device.id, capability_key=capability_key)
        db.add(row)
        # Flush (not commit) immediately -- every session in this
        # project is autoflush=False (app/db/session.py), so a second
        # call to this function for the SAME capability_key later in
        # the same request (e.g. a key present in both
        # `runtime_capabilities` and `model_status`) would otherwise
        # not see this pending INSERT via its own SELECT and would
        # create a second, colliding row, tripping the
        # uq_device_capabilities_device_key constraint at commit time.
        db.flush()
    return row


def sync_from_device_capabilities(db: Session, device: Device) -> None:
    """Marks every key in `Device.capabilities` as `supported=True`.
    Called on registration and whenever a device's declared capability
    list is updated."""
    for key in device.capabilities or []:
        row = _get_or_create(db, device, key)
        row.supported = True
    db.commit()


def sync_from_health_report(db: Session, device: Device, health_report: DeviceHealthReport) -> None:
    """Called immediately after a health report is persisted (the
    existing `edge_sync_service.process_health_report`) -- see Section
    7's "reuse the... health information" instruction."""
    for key in health_report.runtime_capabilities or []:
        row = _get_or_create(db, device, key)
        row.installed = True
        row.available_and_ready = True
        row.last_reported_at = health_report.reported_at

    model_status = health_report.model_status or {}
    for key, status in model_status.items():
        if not isinstance(status, dict):
            continue
        if "healthy" not in status:
            continue
        row = _get_or_create(db, device, key)
        row.healthy = bool(status["healthy"])
        row.last_verified_at = health_report.reported_at
    db.commit()


def list_for_device(db: Session, organization_id: str, device_id: str) -> list[DeviceCapability]:
    stmt = (
        select(DeviceCapability)
        .where(DeviceCapability.organization_id == organization_id, DeviceCapability.device_id == device_id)
        .order_by(DeviceCapability.capability_key.asc())
    )
    return list(db.execute(stmt).scalars().all())


def fleet_capability_summary(db: Session, organization_id: str, *, settings: Settings, now: Optional[datetime] = None) -> list[dict]:
    """Section 7: fleet-wide capability discovery -- for each distinct
    capability_key this organization has ever reported, how many
    devices currently sit in each of the five states. Computed live
    from `device_capabilities`, never cached/pre-aggregated.
    `recently_verified_count` is time-windowed (within
    FLEET_CAPABILITY_RECENTLY_VERIFIED_WINDOW_SECONDS of `now`) --
    distinct from `healthy_count`, which reflects the most recent
    verification regardless of age."""
    now = now or datetime.now(timezone.utc)
    stmt = select(DeviceCapability).where(DeviceCapability.organization_id == organization_id)
    rows = list(db.execute(stmt).scalars().all())
    by_key: dict[str, dict] = {}
    for row in rows:
        bucket = by_key.setdefault(row.capability_key, {
            "capability_key": row.capability_key, "device_count": 0, "supported_count": 0,
            "installed_count": 0, "available_and_ready_count": 0, "healthy_count": 0, "recently_verified_count": 0,
        })
        bucket["device_count"] += 1
        bucket["supported_count"] += int(row.supported)
        bucket["installed_count"] += int(row.installed)
        bucket["available_and_ready_count"] += int(row.available_and_ready)
        bucket["healthy_count"] += int(bool(row.healthy))
        last_verified_at = ensure_utc(row.last_verified_at)
        if last_verified_at is not None and (now - last_verified_at).total_seconds() <= settings.FLEET_CAPABILITY_RECENTLY_VERIFIED_WINDOW_SECONDS:
            bucket["recently_verified_count"] += 1
    return sorted(by_key.values(), key=lambda b: b["capability_key"])
