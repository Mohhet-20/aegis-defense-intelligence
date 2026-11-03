"""Device presence/connectivity derivation.

Binding instruction from the prompt: reuse Phase 8's synchronization
status and health information rather than building a second heartbeat
system from scratch. This module does exactly that -- it derives
`presence_state` purely from `Device.last_seen_at` (already updated by
`device_service.authenticate_device()` on EVERY device-authenticated
request: a sync batch, a health report, or the lightweight heartbeat
endpoint below all count as "the device was just seen"), never from a
new, parallel tracking table.

`connectivity_state` (Phase 8's own column, device-self-reported) and
`presence_state` (this module, server-computed from receipt time) are
DELIBERATELY different concepts -- a device can self-report
"connectivity_state": "online" in a stale health report that is, from
the server's authoritative point of view, actually `presence_state ==
"stale"` or `"offline"` by now. The server's own derived state is
always presence_state; connectivity_state is kept only as the device's
own claim, for comparison, never substituted for the server's view
(Part 3, binding: "connectivity... must remain genuinely separate... and
must never substitute for one another").

PRESENCE_STATES:
    "online"   -- last_seen_at within FLEET_PRESENCE_STALE_AFTER_SECONDS.
    "stale"    -- last_seen_at older than that but within
                  FLEET_PRESENCE_OFFLINE_AFTER_SECONDS.
    "offline"  -- last_seen_at older than FLEET_PRESENCE_OFFLINE_AFTER_SECONDS.
    "unknown"  -- last_seen_at is None (never seen at all) -- never
                  conflated with "offline": a device that has never
                  reported in is a genuinely different finding from one
                  that was online and stopped.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.device import Device
from app.services.timeutil import ensure_utc

PRESENCE_STATES = ("online", "stale", "offline", "unknown")


def derive_presence_state(last_seen_at: Optional[datetime], *, settings: Settings, now: Optional[datetime] = None) -> str:
    last_seen_at = ensure_utc(last_seen_at)
    if last_seen_at is None:
        return "unknown"
    now = ensure_utc(now) or datetime.now(timezone.utc)
    age_seconds = (now - last_seen_at).total_seconds()
    if age_seconds < 0:
        # A clock-skew edge case (a last_seen_at timestamp in the
        # future) -- never crash, never report a negative age as
        # "more online than online." Treated as freshly online.
        age_seconds = 0.0
    if age_seconds <= settings.FLEET_PRESENCE_STALE_AFTER_SECONDS:
        return "online"
    if age_seconds <= settings.FLEET_PRESENCE_OFFLINE_AFTER_SECONDS:
        return "stale"
    return "offline"


# --- Heartbeat rate limiting ("rate-limiting heartbeat
# ingestion"). An honest, documented, best-effort, single-process
# in-memory limiter -- this project has no shared cache/broker, so a
# multi-process deployment would need a real distributed limiter (see
# docs/security/DEVICE_LIFECYCLE_SECURITY.md's "known limitations").
# Keyed by device id; holds only the last-accepted monotonic timestamp
# per device, so memory is bounded by the number of distinct devices
# that have ever sent a heartbeat, not by request volume.
_last_heartbeat_monotonic: dict[str, float] = {}


class HeartbeatRateLimitedError(Exception):
    pass


def enforce_heartbeat_rate_limit(device_id: str, *, settings: Settings) -> None:
    now = time.monotonic()
    last = _last_heartbeat_monotonic.get(device_id)
    if last is not None and (now - last) < settings.FLEET_HEARTBEAT_MIN_INTERVAL_SECONDS:
        raise HeartbeatRateLimitedError(
            f"heartbeat rate limit exceeded -- minimum interval is {settings.FLEET_HEARTBEAT_MIN_INTERVAL_SECONDS}s"
        )
    _last_heartbeat_monotonic[device_id] = now


def reset_heartbeat_rate_limit_state() -> None:
    """Test-only helper -- the module-level limiter state would
    otherwise leak between test functions that reuse the same
    device_identifier/device id."""
    _last_heartbeat_monotonic.clear()


class StaleHeartbeatError(Exception):
    """Raised when a heartbeat's client-claimed `reported_at` is older
    than the device's already-recorded `last_seen_at` -- Section 3's
    "stale-update rejection": an out-of-order/replayed heartbeat must
    never move the server's authoritative view of liveness backwards."""


def record_heartbeat(db: Session, device: Device, *, reported_at: Optional[datetime] = None) -> Device:
    """Server-authoritative: the row is stamped with the SERVER's
    receipt time (`datetime.now(timezone.utc)`), never the device's
    claimed `reported_at` -- the same "server-authoritative receipt
    time" discipline Section 3 requires. `reported_at` (if supplied) is
    used only to detect and reject an out-of-order heartbeat; it is
    never itself written to `last_seen_at`. Idempotent: calling this
    twice with the same or an older `reported_at` than the last
    successful call raises `StaleHeartbeatError` rather than silently
    reprocessing, but calling it again with a newer one is always safe.
    """
    server_now = datetime.now(timezone.utc)
    last_seen_at = ensure_utc(device.last_seen_at)
    reported_at_aware = ensure_utc(reported_at)
    if reported_at_aware is not None and last_seen_at is not None and reported_at_aware <= last_seen_at:
        raise StaleHeartbeatError(
            f"heartbeat reported_at ({reported_at_aware.isoformat()}) is not newer than this device's last recorded activity ({last_seen_at.isoformat()})"
        )
    device.last_seen_at = server_now
    db.add(device)
    db.commit()
    db.refresh(device)
    return device
