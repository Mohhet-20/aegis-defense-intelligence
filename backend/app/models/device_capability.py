"""Per-device capability discovery. Deliberately
FIVE separate boolean/timestamp fields, never collapsed into one status
string -- Part 7 is explicit that "supported," "installed,"
"available-and-ready," "healthy," and "recently-verified" are five
genuinely different states a capability can be in, and a device can be
in any combination of them (e.g. a capability can be installed but not
currently healthy, or supported by the device's hardware but never
installed).

`supported`/`installed`/`available_and_ready` are DEVICE-REPORTED --
taken at face value from the device's own self-description the same
way `Device.capabilities`/`inference_backends` always have been
(advisory, never trusted for authorization). `healthy` and
`last_verified_at` are SERVER-COMPUTED from the device's own
DeviceHealthReport history (`model_status`/`runtime_capabilities`) --
never inferred from the device-reported fields alone, so a device
claiming "installed and ready" that has never actually reported a
healthy model status stays `healthy=None` (unknown), not silently
upgraded to healthy. See docs/architecture/FLEET_MANAGEMENT.md Section 4.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

CAPABILITY_SOURCES = ("device_reported", "server_computed")


class DeviceCapability(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "device_capabilities"
    __table_args__ = (
        UniqueConstraint("device_id", "capability_key", name="uq_device_capabilities_device_key"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)

    capability_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Device-reported (face-value, never trusted for authorization).
    supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    installed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    available_and_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Server-computed from health-report history. None means "never
    # verified," not "unhealthy" -- absence is not a negative finding,
    # same discipline as every other optional measurement in this
    # project (see app/models/mixins.py's GeoLocationMixin docstring).
    healthy: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    last_reported_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
