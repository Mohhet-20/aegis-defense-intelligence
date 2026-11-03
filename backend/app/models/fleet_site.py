"""Fleet sites/deployment groups. A `FleetSite` is
an organizational grouping of devices -- "the warehouse sensor cluster,"
"forward base alpha" -- distinct from `Device.deployment_label` (a
free-text self-description a device reports about itself) the same way
`Sensor.lifecycle_status` stayed distinct from `Sensor.status` in
Phase 6: two genuinely different concerns that happen to live on
related rows never collapse into one field.

Deliberately reuses `GeoLocationMixin` (Phase 7) for optional
coordinates rather than inventing a second latitude/longitude pair --
Phase 9 Part 6 explicitly says "reuse the existing geospatial module...
never duplicate." A site with no coordinates is simply a logical
grouping with no map position, never defaulted to (0, 0) -- see
GeoLocationMixin's own docstring.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.mixins import GeoLocationMixin


class FleetSite(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, GeoLocationMixin):
    __tablename__ = "fleet_sites"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
