"""Device registry and lifecycle. Enrollment,
credential issuance/rotation, and administrative lifecycle transitions
for edge devices. See app/models/device.py and
docs/security/EDGE_DEVICE_SECURITY.md.

Binding rule (Part 3): enrollment must never silently grant
unrestricted administrative access. A freshly registered device always
starts `administrative_status="pending"` and cannot authenticate a
single sync/health request until an explicit `activate()` call moves it
to `active` -- see `authenticate_device()` below, which rejects every
status other than `active`.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.device import DEVICE_ADMINISTRATIVE_STATUSES, Device
from app.models.sync_conflict import SyncConflict
from app.models.sync_record import SyncRecord
from app.services import audit_service


class DuplicateDeviceIdentifierError(ValueError):
    pass


class InvalidDeviceLifecycleTransitionError(ValueError):
    pass


# Terminal once revoked -- Section 3/12: revocation is permanent, a
# revoked device is re-enrolled as a brand new Device row, never
# resurrected. pending->suspended is deliberately not a direct edge: a
# device must be explicitly activated at least once before it can be
# suspended (there is nothing meaningful to "pause" before that).
#
#, Section 8 adds "maintenance" (a temporary, explicit,
# reversible administrative pause -- distinct from "suspended," which
# is the security-suspicion pause) and "decommissioned" (a
# permanent, explicit end-of-life state reached BEFORE "revoked" --
# decommissioning retires hardware; revoking invalidates a credential
# as a security response. Both are legal from "decommissioned," since a
# decommissioned device's credential should still be revocable, but
# nothing else is -- it cannot be reactivated). See
# docs/security/DEVICE_LIFECYCLE_SECURITY.md for the full rationale.
_ADMIN_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"active", "revoked"},
    "active": {"suspended", "maintenance", "decommissioned", "revoked"},
    "suspended": {"active", "revoked"},
    "maintenance": {"active", "decommissioned", "revoked"},
    "decommissioned": {"revoked"},
    "revoked": set(),
}

# Transitions a human operator should see a confirmation preview for
# before performing (Part 8: "confirmation previews for consequential
# actions") -- every one is either hard-to-reverse or immediately
# impacts a live device's ability to sync.
CONSEQUENTIAL_LIFECYCLE_TRANSITIONS = {"suspended", "maintenance", "decommissioned", "revoked"}

# A short, non-secret prefix of the plaintext key -- safe to display in
# the UI ("an operator can tell which key is active without
# re-exposing the secret").
_API_KEY_PREFIX_LENGTH = 10


def _generate_api_key() -> tuple[str, str]:
    """Returns (plaintext_key, prefix). The plaintext value is never
    persisted anywhere -- only its bcrypt hash (via the same
    hash_password() every user password already uses) and this short
    prefix are stored."""
    plaintext = f"edge_{secrets.token_urlsafe(32)}"
    return plaintext, plaintext[:_API_KEY_PREFIX_LENGTH]


def register_device(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: str,
    device_identifier: str,
    device_name: str,
    device_type: str,
    deployment_label: Optional[str] = None,
    capabilities: Optional[list] = None,
    inference_backends: Optional[list] = None,
    model_manifest: Optional[dict] = None,
    metadata_note: Optional[str] = None,
    site_id: Optional[str] = None,
) -> tuple[Device, str]:
    """Creates a new Device in `pending` status and issues its one-time
    plaintext API key. Returns (device, plaintext_api_key) -- the
    caller (the route) is responsible for returning that plaintext
    value to the response exactly once and never logging it."""
    # device_identifier is GLOBALLY unique (not just per-organization) --
    # deliberately, so the device-authenticated sync/health endpoints
    # (Section 12's `X-Device-Id`/`X-Device-Api-Key` headers) can look a
    # device up WITHOUT already knowing its organization_id, the same
    # way the JWT-authenticated `/auth/login` flow looks a user up by
    # email alone. See `get_device_by_global_identifier()` below.
    existing = db.execute(select(Device).where(Device.device_identifier == device_identifier)).scalar_one_or_none()
    if existing is not None:
        raise DuplicateDeviceIdentifierError(f"a device with device_identifier '{device_identifier}' is already registered")

    plaintext_key, prefix = _generate_api_key()
    device = Device(
        organization_id=organization_id,
        device_identifier=device_identifier,
        device_name=device_name,
        device_type=device_type,
        deployment_label=deployment_label,
        capabilities=capabilities or [],
        inference_backends=inference_backends or [],
        model_manifest=model_manifest or {},
        metadata_note=metadata_note,
        api_key_hash=hash_password(plaintext_key),
        api_key_prefix=prefix,
        connectivity_state="unknown",
        sync_status="never_synced",
        administrative_status="pending",
        registered_by_user_id=actor_user_id,
        site_id=site_id,
    )
    db.add(device)
    db.commit()
    db.refresh(device)

    # A device's declared capabilities are
    # discoverable from the moment it registers, not only once it
    # first reports health.
    from app.services import fleet_capability_service

    fleet_capability_service.sync_from_device_capabilities(db, device)

    audit_service.record(
        db, action="device.register", actor_user_id=actor_user_id, organization_id=organization_id,
        target_type="device", target_id=device.id, context_metadata={"device_identifier": device_identifier},
    )
    db.commit()
    return device, plaintext_key


def get_device(db: Session, organization_id: str, device_id: str) -> Optional[Device]:
    stmt = select(Device).where(Device.id == device_id, Device.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def get_device_by_identifier(db: Session, organization_id: str, device_identifier: str) -> Optional[Device]:
    stmt = select(Device).where(Device.organization_id == organization_id, Device.device_identifier == device_identifier)
    return db.execute(stmt).scalar_one_or_none()


def get_device_by_global_identifier(db: Session, device_identifier: str) -> Optional[Device]:
    """device_identifier is globally unique (see register_device) --
    used only by `authenticate_device()` below, where the caller (the
    `require_device_auth` dependency) does not yet know which
    organization the device belongs to."""
    stmt = select(Device).where(Device.device_identifier == device_identifier)
    return db.execute(stmt).scalar_one_or_none()


def list_devices_query(
    organization_id: str, *, administrative_status: Optional[str] = None,
    connectivity_state: Optional[str] = None, search: Optional[str] = None,
):
    stmt = select(Device).where(Device.organization_id == organization_id)
    if administrative_status:
        stmt = stmt.where(Device.administrative_status == administrative_status)
    if connectivity_state:
        stmt = stmt.where(Device.connectivity_state == connectivity_state)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(or_(Device.device_name.ilike(pattern), Device.device_identifier.ilike(pattern), Device.deployment_label.ilike(pattern)))
    return stmt.order_by(Device.created_at.desc())


def transition_administrative_status(
    db: Session, device: Device, *, new_status: str, actor_user_id: str, reason: Optional[str] = None,
) -> Device:
    if new_status not in DEVICE_ADMINISTRATIVE_STATUSES:
        raise InvalidDeviceLifecycleTransitionError(f"'{new_status}' is not a valid administrative_status (must be one of {DEVICE_ADMINISTRATIVE_STATUSES})")
    allowed = _ADMIN_ALLOWED_TRANSITIONS.get(device.administrative_status, set())
    if new_status not in allowed:
        raise InvalidDeviceLifecycleTransitionError(f"cannot transition a device from '{device.administrative_status}' to '{new_status}'")

    previous = device.administrative_status
    device.administrative_status = new_status
    if new_status == "revoked":
        device.revoked_at = datetime.now(timezone.utc)
        device.revoked_reason = reason
        # Defense in depth: a revoked device's credential is invalidated
        # immediately, not merely gated by administrative_status -- even
        # a leaked plaintext key stops verifying once revoked (Section
        # 12: "credential rotation/revocation").
        device.api_key_hash = None
    db.add(device)
    db.commit()
    db.refresh(device)
    audit_service.record(
        db, action="device.lifecycle_transition", actor_user_id=actor_user_id, organization_id=device.organization_id,
        target_type="device", target_id=device.id, context_metadata={"previous_status": previous, "new_status": new_status, "reason": reason},
    )
    db.commit()
    return device


def activate_device(db: Session, device: Device, *, actor_user_id: str, reason: Optional[str] = None) -> Device:
    return transition_administrative_status(db, device, new_status="active", actor_user_id=actor_user_id, reason=reason)


def suspend_device(db: Session, device: Device, *, actor_user_id: str, reason: Optional[str] = None) -> Device:
    return transition_administrative_status(db, device, new_status="suspended", actor_user_id=actor_user_id, reason=reason)


def revoke_device(db: Session, device: Device, *, actor_user_id: str, reason: Optional[str] = None) -> Device:
    return transition_administrative_status(db, device, new_status="revoked", actor_user_id=actor_user_id, reason=reason)


def enter_maintenance(db: Session, device: Device, *, actor_user_id: str, reason: Optional[str] = None) -> Device:
    """Only legal from "active" -- a device that
    isn't active has nothing to pause."""
    return transition_administrative_status(db, device, new_status="maintenance", actor_user_id=actor_user_id, reason=reason)


def decommission_device(db: Session, device: Device, *, actor_user_id: str, reason: Optional[str] = None) -> Device:
    """Permanent end-of-life, legal from "active" or
    "maintenance." Deliberately does NOT touch api_key_hash (unlike
    revoke()) -- a decommissioned device is already blocked from
    authenticating because authenticate_device() only accepts
    administrative_status=="active"; the credential itself is left
    alone so a later explicit revoke() still has something to describe
    invalidating in its audit trail. No historical SyncRecord/
    DeviceHealthReport/audit row is ever deleted as part of this call
    (Part 8: "no deletion of historical evidence on decommission")."""
    return transition_administrative_status(db, device, new_status="decommissioned", actor_user_id=actor_user_id, reason=reason)


def preview_lifecycle_transition(db: Session, device: Device, *, new_status: str) -> dict:
    """"confirmation previews for consequential
    actions." Returns, without making any change, whether the
    transition is legal and what it will concretely affect -- read by
    the Fleet Operations Center before it shows a confirm dialog for
    any CONSEQUENTIAL_LIFECYCLE_TRANSITIONS target."""
    allowed = new_status in _ADMIN_ALLOWED_TRANSITIONS.get(device.administrative_status, set())
    impact: list[str] = []
    if new_status in ("suspended", "maintenance", "decommissioned", "revoked"):
        pending = compute_pending_sync_count(db, device.organization_id, device.id)
        if pending:
            impact.append(f"{pending} sync record(s) are currently pending/in-flight for this device and will stop progressing once it can no longer authenticate.")
        impact.append("The device will immediately be rejected by every device-authenticated endpoint (sync, health, heartbeat) until reactivated.")
    if new_status == "revoked":
        impact.append("The device's API key is invalidated immediately and permanently -- this device can never be reactivated; re-enrollment requires a brand new device record.")
    if new_status == "decommissioned":
        impact.append("This is intended as a permanent retirement. Historical sync/health/audit records are preserved, never deleted.")
    return {
        "current_status": device.administrative_status,
        "target_status": new_status,
        "is_legal": allowed,
        "is_consequential": new_status in CONSEQUENTIAL_LIFECYCLE_TRANSITIONS,
        "impact_notes": impact,
    }


def rotate_api_key(db: Session, device: Device, *, actor_user_id: str) -> tuple[Device, str]:
    """Issues a brand-new plaintext key, invalidating the old one
    immediately. Disallowed on a revoked device -- rotate
    is for an active/pending/suspended device recovering from a
    suspected leak, not a way to resurrect a revoked one."""
    if device.administrative_status == "revoked":
        raise InvalidDeviceLifecycleTransitionError("cannot rotate the API key of a revoked device -- re-register a new device instead")
    plaintext_key, prefix = _generate_api_key()
    device.api_key_hash = hash_password(plaintext_key)
    device.api_key_prefix = prefix
    db.add(device)
    db.commit()
    db.refresh(device)
    audit_service.record(
        db, action="device.rotate_api_key", actor_user_id=actor_user_id, organization_id=device.organization_id,
        target_type="device", target_id=device.id,
    )
    db.commit()
    return device, plaintext_key


def authenticate_device(db: Session, device_identifier: str, plaintext_api_key: str) -> Optional[Device]:
    """Used by the `require_device_auth` FastAPI dependency.
    Returns the Device only if: it exists (looked up GLOBALLY by its
    unique device_identifier -- the caller does not yet know its
    organization_id), is `active` (never `pending`/`suspended`/`revoked`
    -- Part 3's binding "enrollment never silently grants unrestricted
    access"), and the supplied key verifies against the stored bcrypt
    hash. Updates `last_seen_at` on success -- a device-auth check IS
    the liveness signal in this architecture, since every
    device-authenticated endpoint requires it."""
    device = get_device_by_global_identifier(db, device_identifier)
    if device is None or device.administrative_status != "active" or device.api_key_hash is None:
        return None
    if not verify_password(plaintext_api_key, device.api_key_hash):
        return None
    device.last_seen_at = datetime.now(timezone.utc)
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def compute_pending_sync_count(db: Session, organization_id: str, device_id: str) -> int:
    """Live-computed, never read off a stale column (same discipline
    Established for location_validation_status) -- how many
    SyncRecord rows for this device are currently in a non-terminal,
    still-moving-toward-synced state."""
    stmt = select(func.count()).select_from(SyncRecord).where(
        SyncRecord.organization_id == organization_id,
        SyncRecord.device_id == device_id,
        SyncRecord.sync_status.in_(("queued", "syncing", "retryable_failure")),
    )
    return db.scalar(stmt) or 0


def compute_unresolved_conflict_count(db: Session, organization_id: str, device_id: str) -> int:
    stmt = select(func.count()).select_from(SyncConflict).where(
        SyncConflict.organization_id == organization_id,
        SyncConflict.device_id == device_id,
        SyncConflict.resolution_status == "unresolved",
    )
    return db.scalar(stmt) or 0


def to_response(db: Session, device: Device):
    """Builds a `DeviceResponse` with the live-computed
    pending_sync_count/unresolved_conflict_count filled in -- the
    generic `app.api.pagination.paginate()` helper can't do this (it
    only ever calls `response_model.model_validate(row)`), so every
    device list/detail route uses this instead."""
    from app.schemas.device import DeviceResponse

    from app.core.config import get_settings
    from app.services import fleet_presence_service

    response = DeviceResponse.model_validate(device)
    response.pending_sync_count = compute_pending_sync_count(db, device.organization_id, device.id)
    response.unresolved_conflict_count = compute_unresolved_conflict_count(db, device.organization_id, device.id)
    response.presence_state = fleet_presence_service.derive_presence_state(device.last_seen_at, settings=get_settings())
    return response


def get_health_reports_query(organization_id: str, device_id: str):
    from app.models.device_health_report import DeviceHealthReport

    return (
        select(DeviceHealthReport)
        .where(DeviceHealthReport.organization_id == organization_id, DeviceHealthReport.device_id == device_id)
        .order_by(DeviceHealthReport.reported_at.desc())
    )
