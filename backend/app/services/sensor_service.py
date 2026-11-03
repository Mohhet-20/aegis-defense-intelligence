from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from app.models.sensor import SENSOR_LIFECYCLE_STATUSES, Sensor
from app.services import audit_service


class InvalidLifecycleTransitionError(ValueError):
    pass


def create_sensor(db: Session, *, organization_id: str, **fields) -> Sensor:
    sensor = Sensor(organization_id=organization_id, status="unknown", lifecycle_status="registered", **fields)
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor


def get_sensor(db: Session, organization_id: str, sensor_id: str) -> Optional[Sensor]:
    stmt = select(Sensor).where(Sensor.id == sensor_id, Sensor.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_sensors_query(
    organization_id: str, *, category: Optional[str] = None, lifecycle_status: Optional[str] = None,
    sensor_type: Optional[str] = None, measurement_type: Optional[str] = None, search: Optional[str] = None,
):
    stmt = select(Sensor).where(Sensor.organization_id == organization_id)
    if category:
        stmt = stmt.where(Sensor.category == category)
    if lifecycle_status:
        stmt = stmt.where(Sensor.lifecycle_status == lifecycle_status)
    if sensor_type:
        stmt = stmt.where(Sensor.sensor_type == sensor_type)
    if measurement_type:
        # SQLite/Postgres-portable "JSON array contains string" check --
        # a LIKE over the serialized JSON text is imprecise in general,
        # but measurement_type values are simple identifiers (no
        # quote/bracket characters), so this is safe here and avoids a
        # dialect-specific JSON operator. The CAST is required on PostgreSQL:
        # `json LIKE text` is not an operator there (it raised
        # UndefinedFunction -> HTTP 500 before Phase 18).
        stmt = stmt.where(cast(Sensor.measurement_types, String).like(f'%"{measurement_type}"%'))
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(or_(Sensor.name.ilike(pattern), Sensor.description.ilike(pattern)))
    return stmt.order_by(Sensor.created_at.desc())


def update_sensor(db: Session, sensor: Sensor, **fields) -> Sensor:
    for key, value in fields.items():
        if value is not None:
            setattr(sensor, key, value)
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor


# Explicit, documented transitions an analyst may always request (the
# ones app/models/sensor.py's docstring marks "explicit analyst action
# only" -- maintenance/retired in either direction -- plus the simple
# reversible active<->maintenance round trip). An analyst can also move
# a sensor directly out of "degraded"/"offline" back to "active" by
# hand (e.g. after a confirmed physical fix) without waiting for the
# next health recompute.
_ANALYST_ALLOWED_TRANSITIONS = {
    "registered": {"maintenance", "retired", "active"},
    "active": {"maintenance", "retired", "degraded", "offline"},
    "degraded": {"maintenance", "retired", "active"},
    "offline": {"maintenance", "retired", "active"},
    "maintenance": {"active", "retired", "registered"},
    "retired": set(),  # terminal -- never reversible through this function
}


def transition_lifecycle_status(db: Session, sensor: Sensor, *, new_status: str, actor_user_id: str, note: Optional[str] = None) -> Sensor:
    if new_status not in SENSOR_LIFECYCLE_STATUSES:
        raise InvalidLifecycleTransitionError(f"'{new_status}' is not a valid lifecycle_status (must be one of {SENSOR_LIFECYCLE_STATUSES})")
    allowed = _ANALYST_ALLOWED_TRANSITIONS.get(sensor.lifecycle_status, set())
    if new_status not in allowed:
        raise InvalidLifecycleTransitionError(f"cannot transition a sensor from '{sensor.lifecycle_status}' to '{new_status}'")
    previous = sensor.lifecycle_status
    sensor.lifecycle_status = new_status
    if new_status == "retired":
        sensor.retired_at = datetime.now(timezone.utc)
        sensor.retired_by_user_id = actor_user_id
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    audit_service.record(
        db, action="sensor.lifecycle_transition", actor_user_id=actor_user_id, organization_id=sensor.organization_id,
        target_type="sensor", target_id=sensor.id, context_metadata={"previous_status": previous, "new_status": new_status, "note": note},
    )
    db.commit()
    return sensor


def retire_sensor(db: Session, sensor: Sensor, *, actor_user_id: str, note: Optional[str] = None) -> Sensor:
    return transition_lifecycle_status(db, sensor, new_status="retired", actor_user_id=actor_user_id, note=note)


def get_status_history(db: Session, organization_id: str, sensor_id: str) -> list:
    """Reuses the append-only AuditRecord trail rather than a parallel
    per-sensor history table -- same choice Phase 3's
    audit_service.list_for_target() already made for relationship/
    conflict/assessment review history."""
    return audit_service.list_for_target(db, organization_id, target_type="sensor", target_id=sensor_id)
