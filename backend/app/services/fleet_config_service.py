"""Device configuration management: version/baseline assignment,
optimistic-concurrency config updates, and drift detection (Section 8). See app/models/device_config_baseline.py.

Drift is only ever evaluated against an EXPLICIT, assigned baseline --
a device with no baseline assigned returns `evaluated=False`,
`has_drift=None`, never a fabricated "no drift" (Part 8, binding: "a
missing baseline is not an absence of drift," the same discipline
the GeoLocationMixin established for missing coordinates).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.device_config_baseline import DeviceConfigBaseline
from app.services import audit_service


class ConfigRevisionConflictError(ValueError):
    pass


class BaselineNotFoundError(ValueError):
    pass


def create_baseline(
    db: Session, *, organization_id: str, actor_user_id: str, name: str, expected_config: dict,
    description: Optional[str] = None, version: int = 1,
) -> DeviceConfigBaseline:
    baseline = DeviceConfigBaseline(
        organization_id=organization_id, name=name, version=version,
        expected_config=expected_config, description=description, created_by_user_id=actor_user_id,
    )
    db.add(baseline)
    db.commit()
    db.refresh(baseline)
    audit_service.record(
        db, action="fleet.baseline_create", actor_user_id=actor_user_id, organization_id=organization_id,
        target_type="device_config_baseline", target_id=baseline.id, context_metadata={"name": name, "version": version},
    )
    db.commit()
    return baseline


def get_baseline(db: Session, organization_id: str, baseline_id: str) -> Optional[DeviceConfigBaseline]:
    stmt = select(DeviceConfigBaseline).where(DeviceConfigBaseline.id == baseline_id, DeviceConfigBaseline.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_baselines_query(organization_id: str):
    return select(DeviceConfigBaseline).where(DeviceConfigBaseline.organization_id == organization_id).order_by(DeviceConfigBaseline.created_at.desc())


def assign_baseline(db: Session, device: Device, baseline: DeviceConfigBaseline, *, actor_user_id: str) -> Device:
    previous = device.config_baseline_id
    device.config_baseline_id = baseline.id
    db.add(device)
    db.commit()
    db.refresh(device)
    audit_service.record(
        db, action="fleet.baseline_assign", actor_user_id=actor_user_id, organization_id=device.organization_id,
        target_type="device", target_id=device.id, context_metadata={"previous_baseline_id": previous, "new_baseline_id": baseline.id},
    )
    db.commit()
    return device


def update_config(db: Session, device: Device, *, new_config: dict, expected_revision: int, actor_user_id: str) -> Device:
    """Section 8: "optimistic concurrency on config changes." The
    caller must supply the revision it last read -- a mismatch means
    someone else changed the config in between, and this call is
    rejected rather than silently overwriting their change."""
    if device.config_revision != expected_revision:
        raise ConfigRevisionConflictError(
            f"expected_revision {expected_revision} does not match the device's current config_revision {device.config_revision} "
            "-- reload the device's current config and retry"
        )
    previous_config = device.current_config
    device.current_config = new_config
    device.config_revision = device.config_revision + 1
    db.add(device)
    db.commit()
    db.refresh(device)
    audit_service.record(
        db, action="fleet.config_update", actor_user_id=actor_user_id, organization_id=device.organization_id,
        target_type="device", target_id=device.id,
        context_metadata={"previous_revision": expected_revision, "new_revision": device.config_revision, "previous_config": previous_config, "new_config": new_config},
    )
    db.commit()
    return device


def compute_drift(db: Session, device: Device) -> dict:
    """Returns {"evaluated": bool, "has_drift": Optional[bool],
    "baseline_id": Optional[str], "differences": list[dict]}.
    `differences` is a key-by-key comparison of `device.current_config`
    against the assigned baseline's `expected_config` -- every entry
    names the key and both values, never just "something differs.\""""
    if device.config_baseline_id is None:
        return {"evaluated": False, "has_drift": None, "baseline_id": None, "differences": []}
    baseline = get_baseline(db, device.organization_id, device.config_baseline_id)
    if baseline is None:
        # The assigned baseline was deleted out from under the device --
        # still not "no drift," since there is nothing to compare
        # against any more.
        return {"evaluated": False, "has_drift": None, "baseline_id": device.config_baseline_id, "differences": []}

    current = device.current_config or {}
    expected = baseline.expected_config or {}
    differences: list[dict] = []
    for key in sorted(set(current.keys()) | set(expected.keys())):
        current_value = current.get(key)
        expected_value = expected.get(key)
        if current_value != expected_value:
            differences.append({"key": key, "current_value": current_value, "expected_value": expected_value})
    return {
        "evaluated": True, "has_drift": len(differences) > 0, "baseline_id": baseline.id,
        "baseline_version": baseline.version, "differences": differences,
    }
