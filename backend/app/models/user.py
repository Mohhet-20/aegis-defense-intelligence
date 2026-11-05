from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "users"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Validated against app.core.security.Role by the schema layer; kept
    # a plain String column so SQLite and Postgres both accept it
    # without an enum migration (same pattern as a prior system's
    # Incident.status -- see docs/architecture/ARCHITECTURE_DECISIONS.md).
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="viewer")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    # Bumped on password change, role change, disablement and
    # explicit "revoke sessions". Every issued token carries the value at
    # issue time (claim `tv`); a token whose `tv` != the stored value is
    # rejected, so ALL previously issued access AND refresh tokens die.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
