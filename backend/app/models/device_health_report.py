"""Append-only device health report history.
Each row is one self-reported health snapshot a device submitted
through the device-authenticated `POST /edge/sync/health` endpoint --
never edited or deleted, the same append-only discipline every other
historical record in this codebase follows. `Device.last_health_report_at`
and the device's live-derived fields are a convenience summary of the
MOST RECENT row here; this table is the actual history the Device
Detail page's "Health history" tab reads from.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime


class DeviceHealthReport(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "device_health_reports"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)

    reported_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    connectivity_state: Mapped[str] = mapped_column(String(20), nullable=False)

    # Free-form but bounded by the schema layer (app/schemas/edge_sync.py)
    # -- battery/CPU/disk/memory, whatever the device chooses to report.
    # Never assumed present; a device that doesn't report a metric
    # leaves it out, never defaulted to 0 (same "absence is not zero"
    # discipline as every other optional measurement in this project).
    resource_metrics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    queue_depth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pending_sync_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model_status: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    software_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    runtime_capabilities: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
