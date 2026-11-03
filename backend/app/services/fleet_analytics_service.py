"""Fleet analytics / SLIs. Every number returned
here is computed live from currently-persisted rows at call time --
there is no background aggregation job and no stored "trend" series.
Each metric's docstring/comment states its numerator, denominator, and
time window explicitly; nothing here extrapolates a historical trend
from a single snapshot (Part 13, binding: "no fabricated historical
trends" -- this module simply does not offer a trend at all yet,
rather than inventing one from one data point).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.device import Device
from app.models.infrastructure_alert import InfrastructureAlert
from app.models.sync_conflict import SyncConflict
from app.services import fleet_presence_service


def fleet_overview(db: Session, organization_id: str, *, settings: Optional[Settings] = None, now: Optional[datetime] = None) -> dict:
    """Snapshot-at-`now` fleet summary. Denominator for every
    *_percent/*_count figure below is "all Device rows in this
    organization right now" unless stated otherwise."""
    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)

    devices = list(db.execute(select(Device).where(Device.organization_id == organization_id)).scalars().all())
    total_devices = len(devices)

    presence_counts: dict[str, int] = {state: 0 for state in fleet_presence_service.PRESENCE_STATES}
    administrative_status_counts: dict[str, int] = {}
    devices_with_assigned_baseline = 0
    for device in devices:
        presence = fleet_presence_service.derive_presence_state(device.last_seen_at, settings=settings, now=now)
        presence_counts[presence] += 1
        administrative_status_counts[device.administrative_status] = administrative_status_counts.get(device.administrative_status, 0) + 1
        if device.config_baseline_id is not None:
            devices_with_assigned_baseline += 1

    # Open alert counts by severity -- numerator: InfrastructureAlert
    # rows for this org with status in (open, acknowledged, reopened);
    # denominator: not applicable, this is a raw count, not a ratio.
    open_alert_rows = list(db.execute(
        select(InfrastructureAlert.severity, func.count()).where(
            InfrastructureAlert.organization_id == organization_id,
            InfrastructureAlert.status.in_(("open", "acknowledged", "reopened")),
        ).group_by(InfrastructureAlert.severity)
    ).all())
    open_alerts_by_severity = {severity: count for severity, count in open_alert_rows}
    total_open_alerts = sum(open_alerts_by_severity.values())

    # Unresolved sync conflicts fleet-wide -- numerator: SyncConflict
    # rows with resolution_status="unresolved"; denominator: not
    # applicable, raw count (mirrors device_service.compute_unresolved_conflict_count
    # but fleet-wide instead of per-device).
    unresolved_conflicts = db.scalar(
        select(func.count()).select_from(SyncConflict).where(SyncConflict.organization_id == organization_id, SyncConflict.resolution_status == "unresolved")
    ) or 0

    return {
        "as_of": now,
        "total_devices": total_devices,
        "presence_counts": presence_counts,
        "administrative_status_counts": administrative_status_counts,
        "devices_with_assigned_baseline": devices_with_assigned_baseline,
        # Percent of devices with ANY baseline assigned (not drift --
        # drift requires evaluating each one, which the overview does
        # not do per-device for cost reasons; see the per-device detail
        # endpoint for an individual device's drift status).
        "baseline_assignment_pct": round(100.0 * devices_with_assigned_baseline / total_devices, 1) if total_devices else None,
        "open_alerts_by_severity": open_alerts_by_severity,
        "total_open_alerts": total_open_alerts,
        "unresolved_sync_conflicts": unresolved_conflicts,
    }
