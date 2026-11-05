# Enterprise Fleet Management Architecture

**Status: IMPLEMENTED, tested, in SIMULATION ONLY.** No physical edge
hardware is available in this environment -- see
`docs/architecture/EDGE_ARCHITECTURE.md` Section 18.
This document extends, and does not replace,
`docs/architecture/EDGE_ARCHITECTURE.md` -- device identity,
credentials, the sync protocol, and the two-tier conflict policy stay
exactly where left them. Everything below is new fleet-level
observability and administration built *on top of* that foundation, .

## 1. Scope and non-scope, stated first

Delivers: server-computed presence derivation reusing
the edge-sync layer's `Device.last_seen_at`; a standardized health-finding rule engine
with explicit measurement-quality discipline; per-device capability
discovery across five independent states; fleet sites/deployment
groups; configuration baselines with optimistic-concurrency updates and
drift detection; a dedicated fleet-health infrastructure-alerting
system with service-layer deduplication; an extended administrative
lifecycle (`maintenance`/`decommissioned`) with confirmation-preview
support; and a live, point-in-time fleet analytics snapshot. It does
**not** deliver: automatic promotion of a `SyncRecord` into a canonical
domain row (still the stated deferral, unchanged by this
layer), any background scheduler (nothing here runs on a timer --
alerts are (re-)evaluated synchronously on every health-report
submission, exactly as each layer's job-execution model has
been request/response only), a distributed/multi-process-safe rate
limiter (Section 9 below), or stored historical trend series anywhere
(`fleet_analytics_service.py`'s own module docstring is explicit about
this). Strictly defensive scope, confirmed clean: no
autonomous targeting, weapon control, engagement logic, or remote
weapon interface exists anywhere in the new models, services, or
routes -- this is pure fleet observability/administration tooling, the
same honest statement every earlier work has made about its own scope.

## 2. Components and how they fit together

| Component | Where | Role |
|---|---|---|
| Presence derivation + heartbeat | `app/services/fleet_presence_service.py`, `app/api/routes/edge_presence.py` | Server-computed `presence_state` from `Device.last_seen_at`; a lightweight heartbeat endpoint for a device with nothing else to sync. |
| Health-finding rules | `app/services/fleet_health_service.py` | Standardized findings (presence/disk/battery/queue-depth) over the device's own reported metrics and the server's own presence computation. |
| Capability discovery | `app/models/device_capability.py`, `app/services/fleet_capability_service.py`, `app/api/routes/fleet_capabilities.py` | Five independent per-(device, capability) states, fleet-wide rollup. |
| Configuration baselines + drift | `app/models/device_config_baseline.py`, `app/services/fleet_config_service.py`, `app/api/routes/fleet_config.py` | Authorized configuration intent, optimistic-concurrency updates, key-by-key drift comparison. |
| Infrastructure alerting | `app/models/infrastructure_alert.py`, `app/services/fleet_alert_service.py`, `app/api/routes/infra_alerts.py` | Deduplicated, auditable fleet-health alert queue, deliberately separate from intelligence alerting. |
| Fleet sites/groups | `app/models/fleet_site.py`, `app/services/fleet_site_service.py`, `app/api/routes/fleet_sites.py` | Deployment-location grouping, reusing the `GeoLocationMixin`. |
| Extended administrative lifecycle | `app/services/device_service.py` (`enter_maintenance`, `decommission_device`, `preview_lifecycle_transition`), `app/api/routes/edge_devices.py` | Adds `maintenance`/`decommissioned` states and a read-only confirmation preview to the lifecycle. |
| Fleet analytics | `app/services/fleet_analytics_service.py`, `app/api/routes/fleet_analytics.py` | A single live snapshot endpoint over devices/alerts/sync-conflicts. |
| Security/config | `app/core/security.py` (5 new `Permission`s), `app/core/config.py` (`FLEET_*` settings) | RBAC and configurable thresholds for everything above. |
| Frontend (Fleet Operations Center) | `frontend/src/pages/fleet/*`, plus `EdgeDeviceListPage.tsx`/`EdgeDeviceDetailPage.tsx` extensions -- built this layer and independently verified via a clean `tsc`/`build`/`lint` pass (see `docs/testing/FLEET_TESTING.md` Section 4) | Overview/Sites/Alerts pages and (per the device detail page) capability/config/lifecycle tabs. |

Reused, not duplicated: `Device.last_seen_at` (updated by
every device-authenticated request) is the *only* liveness signal
presence derivation reads -- no second heartbeat-tracking table exists.
`Device.capabilities`/`inference_backends` (self-reported at
registration) and the existing `HealthReportRequest.runtime_capabilities`/
`model_status` fields (the health-report schema, unchanged) are
the only inputs to capability discovery -- no new device-reporting
channel was added. `GeoLocationMixin` is reused verbatim for
`FleetSite` coordinates. `audit_service.record()` is called from every
new state-changing function in every new service module, the same
discipline every earlier work has followed. Newly introduced: four
primary-entity tables (`FleetSite`, `DeviceCapability`,
`DeviceConfigBaseline`, `InfrastructureAlert`); five new columns on the
existing `devices` table (`site_id`, `config_revision`,
`config_baseline_id`, `current_config`, `last_resource_metrics`); seven
new service modules; one new schema module (`app/schemas/fleet.py`);
six new route modules (one of them, `edge_presence.py`, reusing the
existing `edge_devices.py` prefix family under `/devices`, the other
five mounted under `/fleet/*`).

## 3. The six genuinely separate concepts, and why they are never collapsed

A `Device` row's overall state is the union of six concerns that this
layer (and before it) deliberately keeps as six distinct
fields/subsystems, never folded into one status string:

1. **Connectivity** (`Device.connectivity_state`) -- the
   device-*self-reported* claim about its own network state, taken at
   face value and never verified server-side.
2. **Presence** (`fleet_presence_service.derive_presence_state()`,
   computed, never stored as a column) -- the server's own
   authoritative view of liveness, derived purely from the receipt
   time of the device's last authenticated request
   (`Device.last_seen_at`). A device can self-report
   `connectivity_state: "online"` in a report that is, by the time a
   caller reads it, actually `presence_state == "stale"` or
   `"offline"` -- the two are never substituted for one another (Part
   3, binding).
3. **Synchronization** (`Device.sync_status`, `SyncRecord` --
   the edge-sync layer, unchanged) -- whether the device's submitted records have
   actually landed centrally; entirely independent of whether the
   device is currently reachable.
4. **Administrative lifecycle** (`Device.administrative_status`) --
   whether a human has authorized this device to do anything at all;
   Section 8 below extends this with `maintenance`/`decommissioned`.
5. **Capability** (`DeviceCapability`, five states -- Section 4 below)
   -- what the device can/does run, as distinct from whether it is
   currently alive or synced.
6. **Configuration compliance** (`Device.current_config`/
   `config_baseline_id`, `DeviceConfigBaseline` -- Section 8 below) --
   whether the device's actual configuration matches what an operator
   authorized it to run, independent of every concern above.

Each concern has its own field(s), its own service, and (where
relevant) its own finding/alert type. A device can be simultaneously
`connectivity_state="online"` (self-reported), `presence_state="stale"`
(server-computed), `sync_status="synced"`, `administrative_status="active"`,
missing a required capability, and configuration-drifted -- six
independent true statements, all surfaced separately, never merged into
one "fleet health score."

## 4. Capability discovery's five independent states

`DeviceCapability` (one row per `(device, capability_key)`, unique
constraint `uq_device_capabilities_device_key`) tracks five booleans/
timestamps that are each independently true or false -- see
`app/models/device_capability.py`'s own module docstring for the full
rationale, summarized here:

| State | Field | Source | Meaning |
|---|---|---|---|
| Supported | `supported` | Device-reported, from `Device.capabilities` | The device's hardware/firmware declares it *can* run this capability. |
| Installed | `installed` | Device-reported, from a health report's `runtime_capabilities` | The device currently has the capability installed. |
| Available-and-ready | `available_and_ready` | Device-reported, same `runtime_capabilities` list | The device considers it ready to invoke right now. |
| Healthy | `healthy` (nullable) | **Server-computed**, from a health report's `model_status` (shape `{capability_key: {"healthy": bool}}`) | Whether the device's own accumulated health-report history last confirmed this capability working. `None` means *never verified* -- not "unhealthy." An absent finding is never a negative one. |
| Recently verified | `last_verified_at` vs. `FLEET_CAPABILITY_RECENTLY_VERIFIED_WINDOW_SECONDS` | Server-computed, from the same `model_status` timestamp | Whether `healthy`'s last confirmation is still fresh. A capability can be `healthy=True` from a confirmation three months ago -- real, but stale, never silently treated as current. |

`fleet_capability_service.sync_from_device_capabilities()` runs on
registration (and whenever a device's declared capability list
changes) and marks every key `supported=True`.
`sync_from_health_report()` runs on every accepted health report (from
`edge_sync_service.process_health_report()`, the existing
ingestion path) and updates `installed`/`available_and_ready` from
`runtime_capabilities`, and `healthy`/`last_verified_at` from
`model_status`. A capability_key mentioned in an older report but
absent from the latest one is **not** silently flipped back to
`False` -- "recently verified" is exactly the signal that distinguishes
a capability nobody has reported in a while from one actively confirmed
working right now.

`fleet_capability_summary()` computes a fleet-wide rollup (device
counts per state, per capability_key) live from the `device_capabilities`
table on every call -- never cached or pre-aggregated.

## 5. Data flow, in prose: from a device request to a fleet-wide view

1. A device makes any device-authenticated request (a sync batch, a
   health report, or a bare heartbeat via `POST /edge/presence/heartbeat`).
   `device_service.authenticate_device()` (unchanged) updates
   `Device.last_seen_at` with the **server's** receipt time, never the
   device's own claimed timestamp.
2. If the request was a health report, `edge_sync_service.process_health_report()`
   (the route, additions inline) persists the
   `DeviceHealthReport` row, mirrors its `resource_metrics` onto
   `Device.last_resource_metrics` (a convenience cache, never
   authoritative -- the report history remains the real record), then
   calls `fleet_capability_service.sync_from_health_report()` and
   `fleet_alert_service.evaluate_alerts_for_device()` in sequence,
   inline, in the same request -- never a second ingestion path, never
   a background job.
3. Any caller (a fleet-list query, a device-detail page, the overview
   dashboard) that wants to know "is this device alive right now" calls
   `fleet_presence_service.derive_presence_state(device.last_seen_at, ...)`
   at read time -- this is why `DeviceResponse.presence_state` is always
   computed fresh in `device_service.to_response()`, never read off a
   stored column.
4. `fleet_health_service.evaluate_health_findings()` combines that same
   presence computation with the device's *latest* `DeviceHealthReport`'s
   `resource_metrics`/`queue_depth` to produce a list of findings (each
   carrying `source`, `as_of`, `severity`, `evidence`) -- see
   `docs/architecture/DEVICE_HEALTH_MODEL.md` for the full rule-by-rule
   detail.
5. `fleet_alert_service.evaluate_alerts_for_device()` (called from step
   2 above, and reusable standalone) re-runs that same finding
   evaluation plus `fleet_config_service.compute_drift()`, and
   upserts/auto-resolves `InfrastructureAlert` rows by `dedup_key` --
   see `docs/operations/INFRASTRUCTURE_ALERTS.md`.
6. `fleet_analytics_service.fleet_overview()` and
   `fleet_site_service.site_summary()` each independently re-derive
   presence/administrative-status counts and open-alert counts live,
   at call time, over the current `devices`/`infrastructure_alerts`
   rows for the organization -- neither reads a cached aggregate, and
   neither extrapolates a trend from a single snapshot.

No step in this pipeline writes to a second, parallel tracking table --
every stage reads from, and writes back onto, the own `Device`/
`DeviceHealthReport` rows or this layer's four new tables, each scoped
to exactly one of the six concerns in Section 3.

## 6. Fleet sites/groups

`FleetSite` (Section 6 of the prompt) is an organizational grouping --
"the warehouse sensor cluster," "forward base alpha" -- deliberately
distinct from `Device.deployment_label` (the free-text
self-description) the same way kept `Sensor.lifecycle_status`
distinct from `Sensor.status`. `FleetSite` reuses `GeoLocationMixin`
 verbatim for optional coordinates rather than inventing a
second latitude/longitude pair -- explicitly requires
reusing the existing geospatial module. A site with no coordinates is
simply a logical grouping with no map position, never defaulted to
`(0, 0)`. `Device.site_id` is nullable and `ON DELETE SET NULL` -- a
device can exist ungrouped, and deleting a site never deletes its
devices. `fleet_site_service.site_summary()` computes, live, the
site's device count broken down by presence state and administrative
status, plus its open-alert count.

## 7. Known gaps, stated honestly (not hidden)

- No background scheduler of any kind exists -- `evaluate_alerts_for_device()`
  is only invoked inline from a health-report submission, which by
  itself could never raise a `device_offline`/`device_stale` alert for
  a device that has gone genuinely silent (submitting a report is
  itself evidence the device is online). This is closed by
  `evaluate_alerts_for_all_devices()` (`app/services/fleet_alert_service.py`),
  an explicit operator/scheduler-triggered sweep exposed as
  `POST /fleet/alerts/evaluate-sweep` (`INFRA_ALERT_MANAGE`), mirroring
  the own `POST /edge/sync/recover-stale` pattern -- see
  `test_sweep_raises_offline_alert_for_a_device_that_never_reported`,
  `test_sweep_is_org_scoped`, and `test_viewer_cannot_trigger_sweep` in
  `backend/tests/test_fleet_alerts.py`. A real deployment would point
  an external cron at this endpoint; this project still has no
  in-process background scheduler of its own, so nothing here invents
  one -- the sweep stays operator/cron-triggered, never automatic.
- The heartbeat rate limiter is a documented, single-process,
  in-memory limiter -- see
  `docs/security/DEVICE_LIFECYCLE_SECURITY.md`'s "known limitations."
- Fleet analytics is a point-in-time snapshot only; there is no stored
  trend series anywhere, by design (Section 1 above).
- The frontend's Fleet Operations Center was built this layer and
  independently verified via a clean `tsc`/`build`/`lint` pass, not a
  live browser click-through -- see `docs/testing/FLEET_TESTING.md`
  Section 4 for exactly what was and was not exercised.
