# Fleet Testing (Phase 9)

**Status: IMPLEMENTED.** 66 new backend tests across 7 new files,
actually re-run fresh in this completion pass (not assumed from an
earlier run). Full backend suite: **784 passed**, 0 failed (718 carried
forward from Phases 1-8 + 66 new this phase). **93% overall line
coverage maintained** (`python -m pytest tests/ -q --cov=app
--cov-report=term-missing`, re-run in this session). This test suite,
like Phase 8's, is **simulation-only** -- see Section 4.

## 1. Backend test files, by what each covers

All seven files use real SQLite-backed `Session` fixtures and/or a real
FastAPI `TestClient` -- never a mocked service layer.

- **`tests/test_fleet_presence.py` (12 tests)** -- `derive_presence_state()`'s
  four states (`unknown` when never seen, `online` when recently seen,
  `stale` then `offline` as age increases), the clock-skew edge case
  (a future `last_seen_at` never crashes or produces a negative age),
  naive (non-tz-aware) datetimes never raising, the heartbeat rate
  limiter enforcing then resetting correctly, `record_heartbeat()`
  rejecting an out-of-order `reported_at` (`StaleHeartbeatError`) and
  being server-authoritative (never writing the client-claimed
  timestamp), the heartbeat API updating presence and being idempotent
  under rapid repeat calls, the heartbeat API requiring device auth,
  429 on a rate-limited rapid repeat, and `presence_state` actually
  appearing on the device API response.
- **`tests/test_fleet_health_and_capabilities.py` (10 tests)** --
  missing metrics producing no finding (Rule 1), disk-usage
  warning/critical threshold crossing, battery being worse the lower
  it is (the `higher_is_worse=False` branch), presence-offline being
  tagged `server_computed` rather than `device_reported`, capability
  sync from registration marking `supported`, the five capability
  states being genuinely independent (via the real API), `healthy`
  staying `None` until an actual verification occurs, the fleet
  capability summary counting correctly per key, the per-device
  capability API requiring `DEVICE_READ`, and the fleet-wide summary
  API.
- **`tests/test_fleet_config_and_drift.py` (7 tests)** -- drift not
  evaluated without a baseline (`evaluated=False`, never "no drift"),
  drift genuinely detected against an assigned baseline, a config that
  matches its baseline showing no drift, optimistic concurrency
  rejecting a stale `expected_revision`, the config-update API
  returning a real `409` on a revision conflict, baseline assignment
  and drift computation walked through the real API, and Viewer being
  forbidden from creating a baseline or updating a device's config.
- **`tests/test_device_lifecycle_phase9.py` (8 tests)** -- `maintenance`
  only being legal from `active`, decommissioning preserving historical
  sync/health rows while blocking reactivation, `maintenance` being
  genuinely distinct from `suspended` (both block auth, different
  audit semantics), the lifecycle preview being read-only and
  correctly reporting impact notes, the preview correctly flagging an
  illegal transition, the preview API, maintenance/decommission walked
  through the real API, and Viewer being forbidden from entering
  maintenance or decommissioning a device.
- **`tests/test_fleet_alerts.py` (11 tests)** -- an offline device
  generating a `critical` alert, repeated evaluation of the same
  condition never duplicating the open alert (dedup in action), a
  recovered device auto-resolving its offline alert with a real
  resolution note, the same `dedup_key` legitimately recurring as a
  brand-new row after a prior occurrence was resolved, the full
  acknowledge/resolve/reopen lifecycle, reopen being legal only from
  `resolved`, the Alert Center API listing and acknowledging an alert,
  config-drift alerting correctly requiring an *evaluated* baseline
  (never alerting on an unevaluated condition), the explicit
  `evaluate-sweep` endpoint raising a `device_offline` alert for a
  device that never reported at all
  (`test_sweep_raises_offline_alert_for_a_device_that_never_reported`),
  the sweep being correctly org-scoped (`test_sweep_is_org_scoped`),
  and Viewer being forbidden from triggering it
  (`test_viewer_cannot_trigger_sweep`).
- **`tests/test_fleet_sites_and_analytics.py` (9 tests)** -- creating a
  site without coordinates never defaulting to `(0, 0)`, assigning a
  device to a site and reading its summary, unassigning a device from
  a site, the fleet overview counting only real devices, tenant
  isolation on the fleet overview (one organization's devices never
  leaking into another's count), the fleet-sites API's full
  create/list/get/summary cycle, Viewer being forbidden from creating a
  site, assigning a device to a site via the real API, and the fleet
  overview API end to end.
- **`tests/test_fleet_routes_additional_coverage.py` (9 tests)** --
  404s on an unknown baseline/site/alert, 404 on assigning a device to
  an unknown site, resolving and reopening an alert through the real
  API, 404s on resolve/reopen of an unknown alert, and Viewer being
  forbidden from resolving or reopening an alert.

**Total new tests this phase: 12 + 10 + 7 + 8 + 11 + 9 + 9 = 66.**
718 (Phases 1-8) + 66 = **784**, matching the real `pytest` run below.

## 2. Coverage, by module (new Phase 9 code)

Re-measured in this session via `python -m pytest tests/ -q --cov=app
--cov-report=term-missing`:

| Module | Line coverage |
|---|---|
| `app/models/device.py` | 100% |
| `app/models/device_capability.py` | 100% |
| `app/models/device_config_baseline.py` | 100% |
| `app/models/fleet_site.py` | 100% |
| `app/models/infrastructure_alert.py` | 100% |
| `app/services/fleet_presence_service.py` | 100% |
| `app/services/fleet_site_service.py` | 100% |
| `app/services/fleet_config_service.py` | 97% |
| `app/services/fleet_analytics_service.py` | 97% |
| `app/services/fleet_capability_service.py` | 95% |
| `app/services/device_service.py` | 94% |
| `app/services/fleet_alert_service.py` | 92% |
| `app/api/routes/edge_presence.py` | 92% |
| `app/api/routes/edge_devices.py` | 93% |
| `app/services/fleet_health_service.py` | 88% |
| `app/api/routes/fleet_sites.py` | 97% |
| `app/api/routes/fleet_config.py` | 86% |
| `app/api/routes/fleet_capabilities.py` | 100% |
| `app/api/routes/fleet_analytics.py` | 100% |

**Overall project coverage stayed at 93%** across the full suite --
`fleet_health_service.py`'s lower figure (88%) is mostly a couple of
less-common branches (the `age_seconds < 0` clock-skew clamp, and one
or two metric-absent early-return paths) that the explicit "missing
metric produces no finding" tests exercise for the common cases but
not every permutation; `fleet_config.py`'s 86% is two 404 branches on
`GET` endpoints for a baseline id that was never looked up in that
exact way by a test (the *create* and *list* paths, and the
device-side baseline-assignment 404 path, are fully covered via
`test_fleet_routes_additional_coverage.py`).

## 3. A real bug found and fixed during testing

While writing `tests/test_fleet_health_and_capabilities.py`'s
"five capability states are genuinely independent" test (submitting a
health report whose `runtime_capabilities` and `model_status` both
named the same `capability_key`), `fleet_capability_service._get_or_create()`
raised a `UNIQUE constraint failed` error on
`uq_device_capabilities_device_key` the second time it was called for
that key within the same request. Root cause: every DB session in this
project is `autoflush=False` (`app/db/session.py`, unchanged since
Phase 1), so the first call's `db.add(row)` was never visible to the
second call's own `SELECT` lookup until an explicit flush or commit --
the second call saw no existing row and tried to `INSERT` a second one.
Fixed by calling `db.flush()` (not `db.commit()`) immediately after
creating a new row inside `_get_or_create()`, so a later lookup within
the *same* request sees the pending insert without prematurely ending
the transaction. This is documented directly in the function's own
code comment, not just in this test-history note.

A second, related issue surfaced in the same area: SQLite round-trips
a `DateTime(timezone=True)` column without its `tzinfo` through some
driver paths, which made `(now - last_verified_at).total_seconds()`
-style arithmetic in `fleet_capability_service.py`/
`fleet_presence_service.py` raise `TypeError: can't subtract
offset-naive and offset-aware datetimes`. Fixed with the same
`_aware()` normalization helper pattern `edge_sync_service.py` already
established for this exact issue in Phase 8 -- reused verbatim, not
reinvented, in both new modules.

## 4. Simulation-only, and the frontend boundary -- stated explicitly

**This entire backend test suite runs in simulation.** No physical
edge hardware is available in this environment (unchanged from every
statement Phase 8 made about this -- see
`docs/architecture/EDGE_ARCHITECTURE.md` Section 18). Every
device-authenticated call in these tests goes through a real FastAPI
`TestClient` against a real (in-memory SQLite) database -- never a
mocked service layer -- but there is no real device hardware, no real
cellular/radio link, and no real intermittent-connectivity network
path anywhere in this test suite, consistent with Phase 8's own
honesty statement.

**The frontend was built this same phase.** `frontend/src/pages/fleet/`
exists and contains `FleetOverviewPage.tsx`, `FleetSitesPage.tsx`, and
`FleetAlertCenterPage.tsx`, routed and added to navigation, plus
extensions to `EdgeDeviceListPage.tsx`/`EdgeDeviceDetailPage.tsx`
(capability/config/lifecycle/site-assignment views). **This frontend
was independently verified this phase via a clean static pass**: run
from `frontend/` itself, `npx tsc -b` (clean, no output), `npm run
build` (built successfully, only Vite's pre-existing chunk-size
informational note), and `npm run lint` (0 errors, 2 pre-existing
warnings unrelated to this phase's work) all passed. **No live
browser click-through or Playwright run was performed** -- that
remains unverified by this effort. The 784-test/93%-coverage figures
above are backend figures; the frontend's own `tsc`/`build`/`lint`
results are reported separately above, not folded into those numbers.

## 5. What is NOT yet covered

- **Multi-process/multi-replica rate-limiter behavior.** The heartbeat
  rate limiter is tested only against its documented single-process,
  in-memory model -- no test (and no real infrastructure in this
  project) exercises it under multiple worker processes or replicas.
  See `docs/security/DEVICE_LIFECYCLE_SECURITY.md` Section 6.
- **Real external notification integrations.** None exist to test --
  `docs/operations/INFRASTRUCTURE_ALERTS.md` Section 1 states plainly
  that no email/SMS/outbound channel is wired up anywhere in this
  project.
- **A frontend end-to-end click-through of the Fleet Operations
  Center.** Not performed as part of this documentation effort (see
  Section 4) -- the frontend was built and its `tsc`/`build`/`lint`
  pass verified, but a live browser click-through remains a reasonable
  next step for a future completion/verification pass.
- **Alert (re-)evaluation driven purely by inline heartbeat traffic**
  (as opposed to a full health-report submission or an explicit
  sweep) -- `evaluate_alerts_for_device()` is still only ever called
  inline from `process_health_report()`; no test exercises a device
  that only ever heartbeats (never sends a full health report) and
  checks whether a `device_offline`/`device_stale` alert is eventually
  raised purely from that inline traffic, because today it would not
  be. This no longer means such an alert can never be raised at all,
  though: the explicit `evaluate-sweep` endpoint evaluates every
  device's presence regardless of whether it has reported recently,
  and that sweep *is* tested (see Section 1's `test_fleet_alerts.py`
  entry and `docs/architecture/FLEET_MANAGEMENT.md` Section 7).
- **Fleet-wide behavior at a large device count.** No test seeds a
  large number of devices and measures the fleet-overview/capability-
  summary query cost at scale -- consistent with every prior phase's
  own stated gap on retention/performance at scale (see
  `docs/operations/LOCAL_STORAGE_AND_RETENTION.md` for the Phase 8
  precedent of documenting this honestly rather than silently).
