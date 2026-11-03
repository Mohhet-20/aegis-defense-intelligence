from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.observation import Observation


def list_observations_query(
    organization_id: str, *, sensor_id: Optional[str] = None, measurement_type: Optional[str] = None,
    validation_status: Optional[str] = None, since: Optional[datetime] = None, until: Optional[datetime] = None,
):
    stmt = select(Observation).where(Observation.organization_id == organization_id)
    if sensor_id:
        stmt = stmt.where(Observation.sensor_id == sensor_id)
    if measurement_type:
        stmt = stmt.where(Observation.observation_type == measurement_type)
    if validation_status:
        stmt = stmt.where(Observation.validation_status == validation_status)
    if since:
        stmt = stmt.where(Observation.observed_at >= since)
    if until:
        stmt = stmt.where(Observation.observed_at <= until)
    return stmt.order_by(Observation.observed_at.desc(), Observation.id)


def get_observation(db: Session, organization_id: str, observation_id: str) -> Optional[Observation]:
    stmt = select(Observation).where(Observation.id == observation_id, Observation.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()
