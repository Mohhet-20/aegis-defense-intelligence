from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.mixins import GeoLocationMixin

ASSET_STATUSES = ("active", "inactive", "archived")


class Asset(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, GeoLocationMixin):
    """An entity of interest (person, vehicle, facility, equipment --
    whatever entity_type the analyst needs). Section 7 explicitly:
    "a missing location is not a location of zero latitude and
    longitude" -- see GeoLocationMixin."""

    __tablename__ = "assets"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)

    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
