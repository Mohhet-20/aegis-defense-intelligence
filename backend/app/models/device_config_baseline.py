"""Authorized device configuration baselines.
A baseline is what a device's `current_config` is EXPECTED to match --
drift detection (fleet_config_service.compute_drift()) is always a
comparison against an explicit, versioned baseline a human authorized,
never an implicit "whatever the device last reported." Distinct from
`Device.software_version`/`protocol_version` (self-reported
build identity) -- a baseline is administrative INTENT, those columns
are self-reported FACT.

Append-only by convention: a baseline is never edited in place once
created (publishing a changed baseline creates a new row with
`version` incremented), so a device's historical "what was it supposed
to match at time T" is always reconstructable from past AuditRecord
entries that reference a specific baseline id.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class DeviceConfigBaseline(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "device_config_baselines"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # The expected configuration shape, compared key-by-key against a
    # device's `current_config` -- see fleet_config_service.compute_drift().
    expected_config: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
