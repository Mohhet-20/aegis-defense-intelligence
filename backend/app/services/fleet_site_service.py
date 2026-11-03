"""Fleet sites/deployment groups. See
app/models/fleet_site.py.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.device import Device
from app.models.fleet_site import FleetSite
from app.models.infrastructure_alert import InfrastructureAlert
from app.services import audit_service, fleet_presence_service


def create_site(db: Session, *, organization_id: str, actor_user_id: str, name: str, description: Optional[str] = None, latitude: Optional[float] = None, longitude: Optional[float] = None) -> FleetSite:
    site = FleetSite(organization_id=organization_id, name=name, description=description, created_by_user_id=actor_user_id)
    if latitude is not None and longitude is not None:
        site.latitude, site.longitude = latitude, longitude
        site.location_origin = "source_reported"
    db.add(site)
    db.commit()
    db.refresh(site)
    audit_service.record(db, action="fleet.site_create", actor_user_id=actor_user_id, organization_id=organization_id, target_type="fleet_site", target_id=site.id, context_metadata={"name": name})
    db.commit()
    return site


def get_site(db: Session, organization_id: str, site_id: str) -> Optional[FleetSite]:
    stmt = select(FleetSite).where(FleetSite.id == site_id, FleetSite.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_sites_query(organization_id: str):
    return select(FleetSite).where(FleetSite.organization_id == organization_id).order_by(FleetSite.name.asc())


def assign_device_to_site(db: Session, device: Device, site: Optional[FleetSite], *, actor_user_id: str) -> Device:
    previous = device.site_id
    device.site_id = site.id if site else None
    db.add(device)
    db.commit()
    db.refresh(device)
    audit_service.record(db, action="fleet.device_site_assign", actor_user_id=actor_user_id, organization_id=device.organization_id, target_type="device", target_id=device.id, context_metadata={"previous_site_id": previous, "new_site_id": device.site_id})
    db.commit()
    return device


def site_summary(db: Session, organization_id: str, site: FleetSite, *, settings: Optional[Settings] = None) -> dict:
    """Org-scoped per-site rollup: device counts by presence state and
    administrative status, plus open alert count -- all live-computed
    from the actual rows, never a cached/stale counter."""
    settings = settings or get_settings()
    devices = list(db.execute(select(Device).where(Device.organization_id == organization_id, Device.site_id == site.id)).scalars().all())
    presence_counts: dict[str, int] = {}
    admin_counts: dict[str, int] = {}
    for device in devices:
        presence = fleet_presence_service.derive_presence_state(device.last_seen_at, settings=settings)
        presence_counts[presence] = presence_counts.get(presence, 0) + 1
        admin_counts[device.administrative_status] = admin_counts.get(device.administrative_status, 0) + 1
    if devices:
        open_alert_count = db.scalar(
            select(func.count()).select_from(InfrastructureAlert).where(
                InfrastructureAlert.organization_id == organization_id,
                InfrastructureAlert.device_id.in_([d.id for d in devices]),
                InfrastructureAlert.status.in_(("open", "acknowledged", "reopened")),
            )
        ) or 0
    else:
        open_alert_count = 0
    return {
        "site_id": site.id, "site_name": site.name, "device_count": len(devices),
        "presence_counts": presence_counts, "administrative_status_counts": admin_counts,
        "open_alert_count": open_alert_count,
    }
