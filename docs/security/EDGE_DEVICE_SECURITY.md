# Edge Device Security (Phase 8)

**Status: IMPLEMENTED, tested.** Device identity, credentials, and the
device-authentication scheme -- deliberately separate from the user-facing
JWT auth model.

## 1. Device identity, enrollment, and lifecycle

A `Device` row is created by `device_service.register_device()`
(JWT-authenticated, `DEVICE_MANAGE`). `device_identifier` is a stable,
human-chosen string, enforced **globally unique across the entire
platform** (not just per-organization) by a lookup-before-insert check
(`DuplicateDeviceIdentifierError` on collision) -- deliberate, so the
device-authenticated endpoints can resolve a device without first knowing
its organization, the same way `/auth/login` resolves a user by email
alone.

Lifecycle (`administrative_status`, `DEVICE_ADMINISTRATIVE_STATUSES`):

```
pending --activate--> active --suspend--> suspended --activate--> active
                         |                                            |
                         +-------------------revoke-------------------+
                                              |
                                              v
                                          revoked (terminal)
```

`pending` is the **only** status a freshly registered device starts in --
enrollment never silently grants unrestricted administrative access.
`pending -> suspended` is deliberately not a direct edge: a device must be
explicitly activated at least once before it can be suspended (there is
nothing meaningful to "pause" before that). `revoked` is terminal -- a
revoked device is re-enrolled as a brand-new `Device` row, never
resurrected; `rotate_api_key()` on a revoked device raises
`InvalidDeviceLifecycleTransitionError` rather than reviving it. Every
transition is enforced by `device_service._ADMIN_ALLOWED_TRANSITIONS` and
audited (`action="device.lifecycle_transition"`, carrying
`previous_status`/`new_status`/`reason`).

## 2. Credentials: hashing, one-time display, rotation, revocation

A device credential is just another secret -- `device_service._generate_api_key()`
produces a plaintext value (`edge_<32 bytes of secrets.token_urlsafe>`) and
stores **only** its bcrypt hash (`hash_password()`, the exact same function
every user password already uses -- no second hashing scheme invented) plus
a short, non-secret `api_key_prefix` (10 chars) safe to display in the UI so
an operator can tell which key is active without re-exposing the secret.

**The plaintext key is shown exactly once** -- at registration
(`DeviceRegistrationResult`) or at explicit key rotation
(`POST /devices/{device_id}/rotate-key`) -- and is never stored or logged in
recoverable form anywhere in this codebase. The frontend's
`OneTimeSecretField` primitive is the only UI surface that ever displays it,
copyable, never re-shown after the page is left.

**Revoking a device clears its `api_key_hash` immediately** --
`transition_administrative_status()` sets `api_key_hash = None` the moment
`administrative_status` becomes `revoked`, as defense in depth beyond just
the status check in `authenticate_device()`: even a leaked plaintext key
stops verifying the instant a device is revoked, because there is no hash
left to verify it against.

Key rotation (`rotate_api_key()`) issues a brand-new plaintext key and
invalidates the old one immediately (the old hash is overwritten, not kept
alongside the new one) -- a device must update its stored credential before
its next sync attempt, or it will fail authentication with the old key.

## 3. The device-auth scheme vs. JWT

Device-authenticated routes (`edge_sync.py`'s `POST /batch` and
`POST /health`) depend on `require_device_auth`
(`app/core/security.py`), which reads two headers:

- `X-Device-Id` -- the device's `device_identifier`.
- `X-Device-Api-Key` -- the plaintext credential.

`device_service.authenticate_device()` looks the device up **globally** by
`device_identifier` (not scoped to an organization, since the caller
doesn't know it yet), and returns the device only if **all** of the
following hold: it exists, `administrative_status == "active"` (never
`pending`/`suspended`/`revoked`), `api_key_hash is not None`, and
`verify_password(plaintext, api_key_hash)` succeeds. A successful
authentication updates `last_seen_at` -- a device-auth check **is** the
liveness signal in this architecture, since every device-authenticated
endpoint requires it.

This is completely separate infrastructure from the user-facing JWT
bearer-token scheme (`app/core/security.py`'s `get_current_user` /
`require_permission`) used by every admin route (`edge_devices.py`,
`edge_sync_admin.py`, `edge_conflicts.py`). A device credential can never
be used to call an admin route, and a user's JWT can never be used to call
a device-authenticated route -- the two dependency chains never overlap.

## 4. Device-id spoofing rejection

A device's credentials authenticate it as exactly one `device_identifier`.
`POST /edge/sync/batch`'s route handler explicitly checks
`payload.device_id != device.device_identifier` and rejects the batch with
HTTP 400 if the request body's self-reported `device_id` doesn't match the
authenticated device's real identity -- a device cannot submit records
claiming to be a different device than the one its own credentials
authenticated as.

## 5. Least privilege: a device has no Role or Permission at all

A `Device` row carries no `Role`, no `Permission`, and no user-style
session. `require_device_auth`'s only output is the `Device` ORM object
itself; the two device-authenticated routes never call `require_permission`
and have no concept of a device-level permission check beyond
"authenticated and active." This is a deliberate, minimal surface: a
device can do exactly two things over the network -- submit a sync batch
for itself, and report its own health -- and nothing else. All
administrative capability (registering, activating, revoking, inspecting,
resolving conflicts, retrying/canceling sync records) requires a real
user's JWT and the matching `Permission`, never a device credential.

## 6. What is explicitly NOT claimed

- **No encryption guarantee beyond TLS-in-a-real-deployment.** This
  codebase assumes a production deployment terminates TLS at the edge
  (same assumption every other credential-bearing endpoint in this project
  already makes for JWTs); nothing here invents an additional
  application-layer encryption scheme for the device credential or the
  sync payload in transit.
- **No remote shell or arbitrary code execution anywhere.** A device
  cannot cause the backend to execute anything beyond the fixed,
  closed-registry `edge_sync_service`/`edge_conflict_service` code paths --
  there is no remote-command, remote-configuration-push-as-code, or
  dynamic-adapter-loading capability (see
  `docs/architecture/EDGE_INFERENCE.md`'s closed-registry discussion).
- **No weapon interface of any kind.** Nothing in `app/edge/`, the device
  model, or the sync protocol issues a command to, or receives a command
  from, any weapon, targeting, or engagement system -- this remains
  strictly a decision-support platform.
- **No claim of hardware-level security** (secure boot, TPM-backed key
  storage, tamper detection) -- those are properties of real device
  hardware this project has never had access to (see
  `docs/architecture/EDGE_ARCHITECTURE.md` Section 18); the credential
  model described here is the server-side half only.

## 7. Known gaps

- Refresh/rotation is manual (an operator or the device itself must call
  `rotate-key`); there is no automatic credential-expiry or forced-rotation
  schedule.
- No device-side secure storage model is specified or tested -- how a real
  device would protect its own plaintext key at rest is out of this
  phase's scope (there is no physical device to specify it for).
- No mutual TLS / device-certificate scheme -- authentication is the
  `X-Device-Id`/`X-Device-Api-Key` header pair only.
