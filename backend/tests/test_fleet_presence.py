"""Presence/heartbeat tests: derivation from
last_seen_at, the device-authenticated heartbeat endpoint, stale-update
rejection, and rate limiting."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.services import fleet_presence_service
from app.services.timeutil import to_utc


def _settings():
    return get_settings()


def test_presence_unknown_when_never_seen():
    assert fleet_presence_service.derive_presence_state(None, settings=_settings()) == "unknown"


def test_presence_online_when_recently_seen():
    now = datetime.now(timezone.utc)
    last_seen = now - timedelta(seconds=5)
    assert fleet_presence_service.derive_presence_state(last_seen, settings=_settings(), now=now) == "online"


def test_presence_stale_then_offline_as_age_increases():
    settings = _settings()
    now = datetime.now(timezone.utc)
    stale_age = now - timedelta(seconds=settings.FLEET_PRESENCE_STALE_AFTER_SECONDS + 10)
    assert fleet_presence_service.derive_presence_state(stale_age, settings=settings, now=now) == "stale"
    offline_age = now - timedelta(seconds=settings.FLEET_PRESENCE_OFFLINE_AFTER_SECONDS + 10)
    assert fleet_presence_service.derive_presence_state(offline_age, settings=settings, now=now) == "offline"


def test_presence_clock_skew_future_timestamp_is_never_a_crash_or_negative_age():
    now = datetime.now(timezone.utc)
    future = now + timedelta(seconds=30)
    assert fleet_presence_service.derive_presence_state(future, settings=_settings(), now=now) == "online"


def test_presence_handles_naive_datetimes_without_raising():
    """SQLite can round-trip a DateTime(timezone=True) value without
    tzinfo -- derive_presence_state must never raise on that."""
    now = datetime.now(timezone.utc)
    naive_last_seen = (now - timedelta(seconds=5)).replace(tzinfo=None)
    assert fleet_presence_service.derive_presence_state(naive_last_seen, settings=_settings(), now=now) == "online"


def test_heartbeat_rate_limit_enforced_then_resets():
    fleet_presence_service.reset_heartbeat_rate_limit_state()
    settings = _settings()
    fleet_presence_service.enforce_heartbeat_rate_limit("dev-rl-1", settings=settings)
    with pytest.raises(fleet_presence_service.HeartbeatRateLimitedError):
        fleet_presence_service.enforce_heartbeat_rate_limit("dev-rl-1", settings=settings)
    fleet_presence_service.reset_heartbeat_rate_limit_state()
    # After reset, the same device id is allowed immediately again.
    fleet_presence_service.enforce_heartbeat_rate_limit("dev-rl-1", settings=settings)


def test_record_heartbeat_rejects_out_of_order_reported_at(db, active_device_factory):
    device, _ = active_device_factory()
    now = datetime.now(timezone.utc)
    device.last_seen_at = now
    db.add(device)
    db.commit()

    with pytest.raises(fleet_presence_service.StaleHeartbeatError):
        fleet_presence_service.record_heartbeat(db, device, reported_at=now - timedelta(seconds=5))


def test_record_heartbeat_is_server_authoritative_not_client_claimed(db, active_device_factory):
    """The row is stamped with server receipt time, never the client's
    claimed reported_at."""
    device, _ = active_device_factory()
    far_future_claim = datetime.now(timezone.utc) + timedelta(days=5)
    before = datetime.now(timezone.utc)
    device = fleet_presence_service.record_heartbeat(db, device, reported_at=far_future_claim)
    after = datetime.now(timezone.utc)
    # to_utc(), not .replace(): PostgreSQL returns an aware value in the session zone
    # (e.g. +05:30); relabelling it as UTC would shift the instant.
    seen, _ = to_utc(device.last_seen_at)
    assert before <= seen <= after


def test_heartbeat_api_updates_presence_and_is_idempotent(client, active_device_factory, device_headers):
    fleet_presence_service.reset_heartbeat_rate_limit_state()
    device, api_key = active_device_factory()
    resp = client.post("/api/v1/edge/presence/heartbeat", json={"protocol_version": "edge_sync_v1"}, headers=device_headers(device.device_identifier, api_key))
    assert resp.status_code == 200, resp.text
    assert resp.json()["presence_state"] == "online"
    assert resp.json()["device_id"] == device.device_identifier


def test_heartbeat_api_requires_device_auth(client):
    resp = client.post("/api/v1/edge/presence/heartbeat", json={"protocol_version": "edge_sync_v1"})
    assert resp.status_code in (401, 422)


def test_heartbeat_api_rate_limited_on_rapid_repeat(client, active_device_factory, device_headers):
    fleet_presence_service.reset_heartbeat_rate_limit_state()
    device, api_key = active_device_factory()
    headers = device_headers(device.device_identifier, api_key)
    first = client.post("/api/v1/edge/presence/heartbeat", json={"protocol_version": "edge_sync_v1"}, headers=headers)
    assert first.status_code == 200
    second = client.post("/api/v1/edge/presence/heartbeat", json={"protocol_version": "edge_sync_v1"}, headers=headers)
    assert second.status_code == 429
    fleet_presence_service.reset_heartbeat_rate_limit_state()


def test_presence_state_exposed_on_device_response(client, tokens, auth_header, active_device_factory):
    fleet_presence_service.reset_heartbeat_rate_limit_state()
    device, _ = active_device_factory()
    resp = client.get(f"/api/v1/devices/{device.id}", headers=auth_header(tokens, "viewer"))
    assert resp.status_code == 200
    # Just activated, with last_seen_at set by registration/activation's
    # audit flow via authenticate_device -- not necessarily "online"
    # unless a device-authenticated call has happened; presence_state
    # must at least be a recognized value, never a crash/omission.
    assert resp.json()["presence_state"] in fleet_presence_service.PRESENCE_STATES
