"""Timestamp helpers -- the one place the platform's time-zone rules live.

Every datetime this platform stores is UTC. Database values are already
timezone-aware UTC (app/db/types.py UTCDateTime); these helpers normalise values
from anywhere else (request bodies, device payloads, files, older code paths).
A naive value is treated as UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple


def ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Aware UTC datetime (same instant), or None. Naive input is taken to be UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def to_utc(value: Optional[datetime]) -> Tuple[Optional[datetime], bool]:
    """Returns (aware UTC datetime or None, assumed_utc) -- assumed_utc is True when
    the input was naive, so callers can say the zone was assumed rather than known."""
    if value is None:
        return None, False
    return ensure_utc(value), value.tzinfo is None


def iso(value: Optional[datetime]) -> Optional[str]:
    aware = ensure_utc(value)
    return aware.isoformat().replace("+00:00", "Z") if aware else None
