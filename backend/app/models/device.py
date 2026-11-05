"""Edge device registry (placeholder, extended for real use in
Section 3). A `Device` is an edge node's IDENTITY and
LIFECYCLE record: who it is, what it can do, and whether it is allowed
to sync anything. It is deliberately separate from `Sensor`,
`Asset`, `Observation`, and `Event` -- a device is the thing that
CAPTURES or FORWARDS those records, never one of them itself. See
docs/architecture/EDGE_ARCHITECTURE.md Section 3.

Device credentials: `api_key_hash` stores a bcrypt hash of the device's
own long-lived credential (the same `hash_password`/`verify_password`
functions app/core/security.py already uses for user passwords -- a
device secret is just another secret, no second hashing scheme
invented). The plaintext key is generated once at registration (or key
rotation) time, returned to the caller exactly once, and never stored
or logged in recoverable form -- see docs/security/EDGE_DEVICE_SECURITY.md.
`api_key_prefix` is a short, non-secret identifying fragment (safe to
display in the UI so an operator can tell which key is active without
re-exposing the secret).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

# Device-level rollup, same vocabulary already shipped --
# recomputed live from SyncRecord rows by device_service, never trusted
# as a stale write-once column (the same "compute live" discipline
# Established for location_validation_status). Kept as a
# column anyway so a direct DB read/export has a reasonable last-known
# value even before any service call recomputes it.
DEVICE_SYNC_STATUSES = ("never_synced", "synced", "pending", "conflict")

# A device must be explicitly activated before it can sync anything
# (Part 3: "enrollment must not silently create unrestricted
# administrative access"). "pending" is the only status a freshly
# registered device starts in.
#
#, Section 8 extends this with two more explicit-only states,
# mirroring exactly how Sensor.lifecycle_status added
# "maintenance"/"retired" as states reachable ONLY by deliberate
# analyst action, never inferred from data:
#   "maintenance"     -- a temporary, explicit administrative pause
#                         distinct from "suspended" (the edge-sync layer: suspected
#                         credential/security issue) -- maintenance is
#                         planned, routine, and always reversible back
#                         to "active."
#   "decommissioned"   -- a permanent administrative retirement BEFORE
#                         credential revocation; distinct from "revoked"
#                         (the edge-sync layer: credential invalidated, security
#                         event) -- decommissioning is the normal
#                         end-of-life path for hardware that is simply
#                         being retired, not a security response. A
#                         decommissioned device's historical SyncRecord/
#                         DeviceHealthReport/audit rows are never
#                         deleted (Part 8: "no deletion of historical
#                         evidence on decommission").
# See device_service.py's `_ADMIN_ALLOWED_TRANSITIONS` for the full,
# explicit transition table and docs/security/DEVICE_LIFECYCLE_SECURITY.md.
DEVICE_ADMINISTRATIVE_STATUSES = ("pending", "active", "suspended", "maintenance", "decommissioned", "revoked")

DEVICE_CONNECTIVITY_STATES = ("online", "offline", "unknown")


class Device(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """Real registry + lifecycle + credential record.
    See docs/architecture/EDGE_ARCHITECTURE.md Section 3 and
    docs/security/EDGE_DEVICE_SECURITY.md for the full field-by-field
    rationale."""

    __tablename__ = "devices"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    # Stable, human-chosen, unique-per-organization external identifier
    # (e.g. "edge-fob-alpha-01") -- distinct from the UUID primary key,
    # used in the sync protocol's `device_id` field and in device-auth
    # headers, because a deployed device's own configuration should
    # name itself something meaningful, not need to know its database
    # UUID.
    device_identifier: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    device_name: Mapped[str] = mapped_column(String(200), nullable=False)
    device_type: Mapped[str] = mapped_column(String(50), nullable=False)
    deployment_label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    software_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    protocol_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # bcrypt hash of the device's long-lived credential -- see module
    # docstring. NULL only for the brief window between row creation and
    # the credential actually being generated (never exposed as NULL
    # over the API once a device is usable).
    api_key_hash: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    api_key_prefix: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Self-reported capability/model metadata -- advisory, never trusted
    # for authorization (authorization is permission + administrative
    # status only). [{"name": "local_capture", ...}] / model manifest
    # shape documented in docs/architecture/EDGE_INFERENCE.md.
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    inference_backends: Mapped[list] = mapped_column(JSON, default=list)
    model_manifest: Mapped[dict] = mapped_column(JSON, default=dict)

    connectivity_state: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    local_storage_status: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    last_seen_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    last_health_report_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    config_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(20), nullable=False, default="never_synced")

    administrative_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    registered_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    metadata_note: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    reported_health: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # --- enterprise fleet management ------------
    # Deployment grouping -- see app/models/fleet_site.py. Optional: a
    # device can exist with no site assigned (ungrouped), never
    # defaulted to a fabricated "default site."
    site_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("fleet_sites.id", ondelete="SET NULL"), nullable=True, index=True)

    # Optimistic-concurrency revision for configuration changes (Part 8:
    # "optimistic concurrency on config changes") -- incremented by
    # fleet_config_service on every accepted config update. A caller
    # must supply the revision it last read; a mismatch is a 409, never
    # a silent overwrite. Deliberately a SEPARATE counter from
    # SyncRecord's `revision`/`base_revision` -- those cover
    # one mutable *synced record type* ("annotation"); this one covers
    # the device's OWN administrative configuration, a different
    # resource entirely.
    config_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # The configuration this device is currently expected to match
    # (Part 8: "configuration-drift detection against an authorized
    # baseline"). NULL means no baseline has been assigned yet -- drift
    # detection is then simply not evaluated (never treated as "no
    # drift"), see fleet_config_service.compute_drift().
    config_baseline_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("device_config_baselines.id", ondelete="SET NULL"), nullable=True)
    current_config: Mapped[dict] = mapped_column(JSON, default=dict)

    # A convenience mirror of the most recent DeviceHealthReport's
    # `resource_metrics` -- NEVER authoritative (device_health_reports
    # remains the real history; this column exists only so a fleet
    # inventory list query doesn't need a join/subquery per row to show
    # a last-known CPU/battery/disk figure). Always device-reported,
    # never fabricated when absent.
    last_resource_metrics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
