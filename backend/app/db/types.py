"""Column types shared by every model."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """A timestamp that is always UTC and always timezone-aware in Python.

    Stored as `timestamp with time zone` on PostgreSQL and as UTC wall time on
    SQLite (which has no time-zone support). Values are converted to UTC before
    storage -- a naive value is taken to be UTC, the platform-wide convention --
    and come back as aware UTC datetimes on every engine, so API responses always
    carry an explicit offset and no caller has to guess.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            return value  # let the driver raise on a genuinely wrong type
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        # SQLite stores the wall-clock text and drops any offset, so store UTC explicitly.
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
