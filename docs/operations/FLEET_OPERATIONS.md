# Fleet Operations Guide

**Status: IMPLEMENTED, tested, SIMULATION ONLY** (no physical edge
hardware -- see `docs/architecture/EDGE_ARCHITECTURE.md` Section 18).
This is an operator's guide to the Fleet Operations Center -- the
pages an Analyst/Administrator (and, for read-only awareness, an
Investigator/Viewer) uses day to day. For the underlying data model,
see `docs/architecture/FLEET_MANAGEMENT.md`; for alert specifics, see
`docs/operations/INFRASTRUCTURE_ALERTS.md`; for the security properties
of the lifecycle actions described here, see
`docs/security/DEVICE_LIFECYCLE_SECURITY.md`.

**Frontend note, stated honestly:** the Fleet Operations Center's
frontend was built this layer and independently verified via a clean
`tsc`/`build`/`lint` pass. `frontend/src/pages/fleet/` contains
`FleetOverviewPage.tsx`, `FleetSitesPage.tsx`, and
`FleetAlertCenterPage.tsx`, routed at `/fleet/overview`, `/fleet/sites`,
`/fleet/alerts`, and `EdgeDeviceListPage.tsx`/`EdgeDeviceDetailPage.tsx`
were extended with the capability/config/lifecycle/site-assignment
views described below. This guide describes the operator workflow the
backend API is designed to support end to end; it does not claim a
live browser click-through was performed -- see
`docs/testing/FLEET_TESTING.md` Section 4 for the exact boundary of
what was and was not tested this layer.

## 1. Fleet Overview page

`GET /api/v1/fleet/analytics/overview` (`FLEET_ANALYTICS_READ`) backs a
single-screen snapshot: total device count, a breakdown by
`presence_state` (`online`/`stale`/`offline`/`unknown`), a breakdown by
`administrative_status`, how many devices have *any* configuration
baseline assigned (and what percentage that is of the fleet), open
alerts broken down by severity, and the fleet-wide unresolved
sync-conflict count (the `SyncConflict`, reused). Everything on
this page is computed live at the moment of the request -- there is no
"last updated" staleness to worry about, and no stored trend line: this
page answers "what is true right now," never "how has this changed
over time" (that is explicitly out of scope this layer -- see
`docs/architecture/FLEET_MANAGEMENT.md` Section 1).

## 2. Fleet Sites page

`GET /api/v1/fleet/sites` / `POST /api/v1/fleet/sites`
(`FLEET_SITE_READ` / `FLEET_SITE_MANAGE`) lists and creates deployment
groupings. Creating a site takes a name, an optional description, and
optional latitude/longitude -- coordinates are entirely optional; a
site with none is simply a logical grouping with no map position
(never defaulted to `(0, 0)`, see `docs/architecture/FLEET_MANAGEMENT.md`
Section 6). `GET /api/v1/fleet/sites/{site_id}/summary` gives a
per-site rollup: device count, presence-state breakdown,
administrative-status breakdown, and open-alert count for just that
site's devices -- useful for an operator managing one physical
location without wading through the whole fleet.

**Assigning a device to a site:** `POST /api/v1/devices/{device_id}/site`
(`DEVICE_MANAGE`) with `{"site_id": "<id>"}`, or `{"site_id": null}` to
unassign it (ungrouped is a valid, explicit state, not an error). This
is audited (`fleet.device_site_assign`, carrying both the previous and
new site id).

## 3. Fleet Alert Center page

`GET /api/v1/fleet/alerts` (`INFRA_ALERT_READ`) lists infrastructure
alerts, filterable by `status`, `severity`, `device_id`, and
`alert_type`. See `docs/operations/INFRASTRUCTURE_ALERTS.md` for the
full alert model, dedup scheme, and lifecycle actions
(`INFRA_ALERT_MANAGE`: acknowledge/resolve/reopen). This is a
*fleet-health* queue -- never confuse it with an intelligence/threat
alert queue; the two are structurally and permission-wise separate.
The page also has an "Evaluate fleet now" button, wired to
`api.infraAlerts.evaluateSweep()` (`POST /fleet/alerts/evaluate-sweep`,
`INFRA_ALERT_MANAGE`), that lets an operator explicitly re-evaluate
every device's presence/health/drift state on demand rather than
waiting on the next health report -- see
`docs/operations/INFRASTRUCTURE_ALERTS.md` Section 5.

## 4. Device detail: capability, config, and lifecycle tabs

Per-device operator actions all live under
`/api/v1/devices/{device_id}/*` (`edge_devices.py`, extending
the edge-sync layer's device registry API):

- **Capabilities** -- `GET /devices/{device_id}/capabilities`
  (`DEVICE_READ`) lists every `(capability_key)` row for the device
  with its five independent states (Section 4 of
  `docs/architecture/FLEET_MANAGEMENT.md`). From an operator's point
  of view: a capability showing `supported=true, installed=false`
  means the hardware can run it but it isn't deployed yet; one showing
  `installed=true, healthy=null` means it's deployed but has never
  actually reported a health status back (not "known broken" -- just
  never verified); one showing `healthy=true` with an old
  `last_verified_at` means it was confirmed working, but that
  confirmation is stale (check
  `FLEET_CAPABILITY_RECENTLY_VERIFIED_WINDOW_SECONDS`, default one
  hour, for the "recently verified" cutoff). The fleet-wide rollup
  (`GET /api/v1/fleet/capabilities/summary`) answers "how many devices
  across the whole org have capability X installed/healthy/recently
  verified" in one call.
- **Configuration and drift** -- `GET /devices/{device_id}/config`
  (`DEVICE_READ`) returns the device's current configuration, its
  `config_revision`, its assigned baseline id (if any), and a computed
  `drift` object. **Reading this response correctly:**
  - `drift.evaluated == false` means no baseline is assigned (or the
    one that was assigned has since been deleted) -- this is **never**
    the same as "no drift." An operator seeing `evaluated: false` should
    assign a baseline before concluding the device is compliant.
  - `drift.evaluated == true, has_drift == false` means the device's
    `current_config` matches its assigned baseline's `expected_config`
    key-for-key -- genuinely compliant.
  - `drift.evaluated == true, has_drift == true` means
    `drift.differences` lists every key that differs, each with both
    the device's current value and the baseline's expected value.
  - **Assigning a baseline:** `POST /devices/{device_id}/config/baseline`
    (`DEVICE_MANAGE`) with `{"baseline_id": "<id>"}`. Baselines
    themselves are created/listed via `POST`/`GET /api/v1/fleet/config-baselines`
    (also `DEVICE_MANAGE`/`DEVICE_READ`) -- a baseline is an
    append-only administrative record (see
    `app/models/device_config_baseline.py`'s module docstring): to
    change what "compliant" means, create a new baseline with an
    incremented `version` rather than editing an existing one in
    place, so historical audit records that reference a specific
    baseline id stay meaningful.
  - **Updating a device's own configuration:** `PUT /devices/{device_id}/config`
    (`DEVICE_MANAGE`) with `{"new_config": {...}, "expected_revision": N}`.
    `expected_revision` must match the device's *current*
    `config_revision` -- if someone else changed the config in between
    your read and your write, this returns `409 Conflict` rather than
    silently overwriting their change. Reload the device's current
    config and retry with the new revision.
- **Lifecycle** -- see Section 5 below.

## 5. The administrative lifecycle: maintenance vs. suspended vs. decommissioned vs. revoked

Already gave every device `pending`/`active`/`suspended`/
`revoked`. This layer adds two more explicit-only states:

| State | Meaning | When an operator should use it |
|---|---|---|
| `suspended` | A **security-suspicion** pause -- something about this device's behavior or credential looked wrong. | A device is behaving suspiciously, a credential may be compromised, or you need to pause it pending investigation. Reversible back to `active`. |
| `maintenance` (new) | A **planned, routine, explicit** administrative pause -- nothing wrong with the device, it is simply being serviced. | You are physically servicing the device, swapping hardware, or doing planned downtime, and want it cleanly blocked from syncing/heartbeating in the meantime without implying anything was wrong with it. Reversible back to `active`, or it can proceed to `decommissioned`/`revoked` directly from `maintenance`. |
| `decommissioned` (new) | A **permanent, planned end-of-life** -- this device's hardware is being retired, normally, not as a security response. | The device is being taken out of service for good (replaced, retired, no longer needed) and this is *not* a security event. Historical sync/health/audit rows are **never deleted** -- a decommissioned device's full history stays queryable. |
| `revoked` | A **permanent security response** -- the device's credential is invalidated immediately and it can never be reactivated; re-enrollment requires a brand-new device row. | The device's credential is known or suspected compromised, or this is the terminal security action after suspension/decommission. |

**The short version an operator needs:** reach for `maintenance` when
nothing is wrong and you expect the device back in service.
Reach for `suspended` when something looks wrong and you want to
investigate before deciding. Reach for `decommissioned` when the
hardware's life is simply over, routinely. Reach for `revoked` only
when you need to permanently and immediately kill a credential as a
security response -- it is the one state nothing can recover from.

**Full transition table** (enforced by
`device_service._ADMIN_ALLOWED_TRANSITIONS`, see
`docs/security/DEVICE_LIFECYCLE_SECURITY.md` for the full rationale):

```
pending --activate--> active
active  --suspend-->        suspended   --activate--> active
active  --enter_maintenance--> maintenance --activate--> active
active  --decommission-->   decommissioned
maintenance --decommission--> decommissioned
{active, suspended, maintenance, decommissioned} --revoke--> revoked (terminal)
decommissioned --revoke--> revoked (the only edge decommissioned allows besides staying put)
```

**Before performing a consequential action, preview it.**
`GET /devices/{device_id}/lifecycle-preview?target_status=<status>`
(`DEVICE_READ`, read-only, makes no change) returns whether the
transition is legal from the device's current state and, for every
`CONSEQUENTIAL_LIFECYCLE_TRANSITIONS` target
(`suspended`/`maintenance`/`decommissioned`/`revoked`), a list of
concrete `impact_notes` -- e.g. how many sync records are currently
pending for this device and will stop progressing, that the device
will immediately be rejected by every device-authenticated endpoint
until reactivated, and (for `revoked` specifically) that this can never
be undone. An operator-facing confirmation dialog should always call
this endpoint first and show its `impact_notes` before the actual
action endpoint (`/activate`, `/suspend`, `/maintenance`,
`/decommission`, `/revoke`) is called.

## 6. Where to look when something looks wrong

- Device shows `presence_state: "offline"` but you expect it to be
  up: check the Alert Center for a `device_offline` alert first (it
  will have fired automatically on the last health-report submission
  that detected the staleness) -- its `evidence` carries the same
  `last_seen_at`/threshold figures the presence computation used.
- Device shows configuration drift you didn't expect: check
  `drift.differences` for the exact keys, and check whether the
  *baseline* was recently changed (a new baseline version with
  different `expected_config` will show every device assigned to it as
  newly drifted, which is expected, not a bug).
- A capability shows `healthy: null`: this means never verified, not
  broken -- check whether the device has ever actually sent a health
  report with a `model_status` entry for that key at all.
