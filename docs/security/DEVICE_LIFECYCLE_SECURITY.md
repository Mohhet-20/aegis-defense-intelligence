# Device Lifecycle Security (Section 8)

**Status: IMPLEMENTED, tested.** This document extends
`docs/security/EDGE_DEVICE_SECURITY.md` -- the credential
model, device-auth header scheme, and least-privilege design described
there are unchanged. This document covers only what adds: the
two new administrative states, the confirmation-preview mechanism, the
historical-evidence-preservation guarantee, device-reported-metadata
discipline for the new capability/health surfaces, and the heartbeat
rate limiter's honestly-documented limitation.

## 1. The full transition table

`device_service._ADMIN_ALLOWED_TRANSITIONS`:

```python
{
    "pending":        {"active", "revoked"},
    "active":         {"suspended", "maintenance", "decommissioned", "revoked"},
    "suspended":      {"active", "revoked"},
    "maintenance":    {"active", "decommissioned", "revoked"},
    "decommissioned": {"revoked"},
    "revoked":        set(),
}
```

Every transition is validated against this table inside
`transition_administrative_status()` and raises
`InvalidDeviceLifecycleTransitionError` (surfaced as HTTP 400) on an
illegal move -- there is no code path that sets
`Device.administrative_status` directly without going through this
check. `revoked` remains terminal, unchanged: nothing is
legal from `revoked`, and a revoked device is re-enrolled as a
brand-new row, never resurrected.

## 2. Why `maintenance`/`decommissioned` are separate from `suspended`/`revoked`

Established `suspended` (a pause triggered by *security
suspicion*) and `revoked` (a *permanent security response* that
immediately invalidates the credential). The fleet layer adds two states that
are superficially similar -- both also stop a device from
authenticating -- but represent a **genuinely different category of
reason**:

- **`maintenance` vs. `suspended`.** Both pause the device. The
  difference is *why*: `suspended` means something about the device's
  behavior or credential looked wrong and an operator wants to
  investigate before deciding what happens next. `maintenance` means
  nothing is wrong at all -- the device is being serviced, routinely,
  on a schedule the operator controls, and is expected to come back.
  Collapsing these into one state would lose exactly the signal that
  matters most to an operator scanning a fleet dashboard: "is this
  device paused because of a security concern, or because someone is
  changing its battery?" Both are reversible back to `active`.
- **`decommissioned` vs. `revoked`.** Both are permanent. The
  difference is again *why*: `decommissioned` is the normal
  end-of-life path for hardware that is simply being retired --
  nothing security-relevant happened. `revoked` is specifically a
  security response: the credential itself is the problem, and it is
  invalidated immediately (`api_key_hash = None`, same as).
  `decommission_device()` **deliberately does not touch
  `api_key_hash`** -- a decommissioned device is already blocked from
  authenticating because `authenticate_device()` only accepts
  `administrative_status == "active"`; the credential is left alone so
  a later, explicit `revoke()` still has something meaningful to
  describe invalidating in its own audit record. Both `maintenance`
  and `decommissioned` can still reach `revoked` (the transition table
  allows it from every non-terminal state) -- a device being serviced
  or retired can still have its credential explicitly revoked if a
  security concern is discovered along the way.

This mirrors the same "two superficially similar fields that are
genuinely separate concerns" discipline established for
`Sensor.lifecycle_status` adding `maintenance`/`retired` as states
reachable only by deliberate analyst action, never inferred from data.

## 3. The confirmation-preview mechanism

`preview_lifecycle_transition(db, device, new_status)` (exposed as
`GET /devices/{device_id}/lifecycle-preview?target_status=<status>`,
`DEVICE_READ`) is a **read-only function that makes no change to any
row**. It returns:

- `is_legal` -- whether the transition table (Section 1) permits this
  move from the device's current state.
- `is_consequential` -- whether `new_status` is in
  `CONSEQUENTIAL_LIFECYCLE_TRANSITIONS = {"suspended", "maintenance",
  "decommissioned", "revoked"}` -- every one of these either is
  hard-to-reverse or immediately impacts a live device's ability to
  sync.
- `impact_notes` -- a list of concrete, human-readable statements:
  how many `SyncRecord`s are currently pending/in-flight for this
  device and will stop progressing (computed live via
  `compute_pending_sync_count()`, never a stale estimate); that the
  device will immediately be rejected by every device-authenticated
  endpoint until reactivated; and, for `revoked` specifically, that
  this can never be undone and re-enrollment requires a brand-new
  device record; and, for `decommissioned` specifically, that
  historical sync/health/audit records are preserved, never deleted.

The Fleet Operations Center is expected to call this endpoint and show
its `impact_notes` in a confirm dialog **before** calling the actual
action endpoint (`/activate`, `/suspend`, `/maintenance`,
`/decommission`, `/revoke`) for any consequential target -- this is
Part 8's binding "confirmation previews for consequential actions"
requirement, satisfied as a genuinely separate, side-effect-free
read, not merely a frontend-only confirm-dialog with no backend
backing.

## 4. Decommissioning never deletes historical evidence

`decommission_device()`'s own docstring states this directly, and it
is structurally true, not just documented: the function only calls
`transition_administrative_status()`, which only ever updates
`Device.administrative_status` (and, for `revoked` specifically,
`revoked_at`/`revoked_reason`/`api_key_hash`) -- it contains no `DELETE`
of any kind. Every `SyncRecord`, `DeviceHealthReport`,
`DeviceCapability`, and `AuditRecord` row referencing a decommissioned
device remains in the database exactly as it was, fully queryable
through the same endpoints (`/devices/{id}/health-reports`,
`/devices/{id}/capabilities`, `/devices/{id}/status-history`) a
still-active device uses. `test_decommission_preserves_historical_rows_and_blocks_reactivation`
exercises this directly: it decommissions a device with existing
health/sync history and asserts those rows are still present and
unchanged afterward.

## 5. Device-reported metadata is untrusted input, everywhere

The same discipline established for `Device.capabilities`/
`connectivity_state` (self-reported, advisory, never used for
authorization) extends to every new surface that ingests
device-reported data:

- `DeviceCapability.supported`/`installed`/`available_and_ready` are
  taken at face value from the device's own self-description
  (`Device.capabilities`, `HealthReportRequest.runtime_capabilities`)
  -- a device claiming a capability is supported/installed is **never**
  itself sufficient to mark it `healthy`. `healthy`/`last_verified_at`
  are computed server-side from the device's own accumulated
  `model_status` history, and a device cannot set `healthy=True`
  directly through any field the server treats as authoritative on its
  own say-so for authorization or compliance purposes -- it is purely
  an observability signal for a human operator.
- `Device.current_config` (what a device is reportedly running) is
  compared against `DeviceConfigBaseline.expected_config` (what a human
  authorized) -- the comparison is always baseline-vs-current, never
  "trust whatever the device last reported as automatically
  compliant." A missing baseline produces `evaluated=False`, never a
  fabricated "compliant."
- `HeartbeatRequest.reported_at` (the device's own claimed timestamp)
  is used **only** to detect and reject an out-of-order/replayed
  heartbeat (`StaleHeartbeatError`, HTTP 409) -- it is never itself
  written to `Device.last_seen_at`. `record_heartbeat()` always stamps
  the row with the **server's own** receipt time
  (`datetime.now(timezone.utc)`), the same "central/server-authoritative
  clock, never a device's own clock" discipline
  `edge_sync_service._get_current_accepted()` already established for
  sync-record ordering. This matters concretely: a device
  with a skewed or malicious clock cannot make its liveness look more
  current than it actually is, and cannot move the server's
  authoritative view of its own liveness backwards by replaying an
  older claimed timestamp.
- Nothing a device self-reports (capabilities, health metrics,
  heartbeat timing, config) is ever used to grant it a `Permission` or
  change its own `administrative_status` -- exactly as the
  "a device has no Role or Permission at all" discipline already
  established, unchanged. Every state-changing action
  described in this document requires a real user's JWT and the
  matching `Permission`, never a device credential.

## 6. Known limitation, stated plainly: the heartbeat rate limiter

`app/services/fleet_presence_service.py`'s `enforce_heartbeat_rate_limit()`
is a **documented, best-effort, single-process, in-memory limiter** --
a module-level `dict[str, float]` keyed by device id, holding only the
last-accepted monotonic timestamp per device (so memory is bounded by
distinct devices ever seen, not by request volume). This is **not** a
distributed or multi-process-safe rate limiter: this project has no
shared cache (Redis or similar) or message broker, and if this backend
were ever deployed behind multiple worker processes or multiple
replicas, each process would enforce the limit independently against
its own in-memory state -- a device could exceed the intended
organization-wide rate by spreading its heartbeats across multiple
processes/replicas, each of which would see a fresh, empty limiter
state.

This is stated here as a **known limitation**, not hidden as a silent
gap: the single-process limiter is correct and fully tested for this
project's current single-process deployment model (unchanged across
the platform -- there is no load balancer or multi-worker
deployment anywhere in this project's actual configuration), and a real
distributed limiter (e.g. a Redis-backed sliding window) is a
reasonable, explicitly-flagged follow-up if this backend is ever
deployed with multiple worker processes.

`reset_heartbeat_rate_limit_state()` exists purely as a test-only
helper to clear this module-level state between test functions that
reuse the same `device_identifier`/device id -- it is never called from
any production code path.

## 7. What is explicitly NOT claimed (extending the own list)

- No change to the credential model, device-auth header scheme, or
  least-privilege design described in
  `docs/security/EDGE_DEVICE_SECURITY.md` -- that document remains the
  authoritative source for those properties.
- No weapon interface of any kind, consistent with each layer's
  own statement -- nothing in the new lifecycle states, capability
  discovery, configuration management, or alerting issues a command to,
  or receives a command from, any weapon, targeting, or engagement
  system.
- No claim that the heartbeat rate limiter, or any other new
  component, has been exercised under real multi-process or
  multi-replica load -- it has been tested only against the
  single-process model this project actually runs (Section 6).
