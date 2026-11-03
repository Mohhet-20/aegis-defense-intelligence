# Phase 9 -- Definition of Done &amp; Final Engineering Report

This is the one-time completion record for Phase 9 (Phase 9:
Enterprise Edge Fleet Management, Device Observability, Health
Monitoring, Capability Inventory, Lifecycle Management, and Operational
Dashboards). For the living, continuously-updated status, see
[`../PROJECT_STATUS.md`](../PROJECT_STATUS.md) instead -- this file is a
snapshot of what was true at the end of this phase.

**This phase was tested in SIMULATION ONLY. No physical edge hardware is
available in this environment.** Every claim below builds on Phase
8's own `Device`/`SyncRecord`/`DeviceHealthReport` foundation, itself
only ever exercised against a real FastAPI application (a live server
or an in-process ASGI transport in tests) -- never actual device
hardware, a real radio/cellular link, or a real intermittent-
connectivity network path. **This documentation effort was backend-
and-docs-only: no frontend code was written, modified, or driven
end-to-end as part of producing this report** -- see Section 13 and
`docs/testing/FLEET_TESTING.md` Section 4 for the exact boundary.

## Definition of Done, organized by this phase's own priority tiers

### Tier 1 -- Core fleet correctness

| Item | Status | Evidence |
|---|---|---|
| Heartbeats, reusing Phase 8's liveness signal | **Fully implemented** | `fleet_presence_service.record_heartbeat()`, `POST /edge/presence/heartbeat`, server-authoritative receipt time, rejects out-of-order `reported_at` |
| Presence derivation, kept separate from device-reported connectivity | **Fully implemented** | `derive_presence_state()` (online/stale/offline/unknown), `connectivity_state` untouched and never substituted |
| Health-report persistence | **Fully implemented (reused)** | Phase 8's `DeviceHealthReport`, unchanged; Phase 9 adds the finding-rule layer over it, never a new storage table |
| Paginated fleet inventory | **Fully implemented (reused)** | `GET /devices` (Phase 8's own endpoint), now additionally exposing `presence_state`/`site_id`/`config_revision`/`config_baseline_id`/`last_resource_metrics` per row |
| Sync-status exposure | **Fully implemented (reused)** | `Device.sync_status`, `pending_sync_count`/`unresolved_conflict_count` (Phase 8, unchanged), fleet-wide `unresolved_sync_conflicts` added in the new analytics overview |

### Tier 2 -- Operational visibility

| Item | Status | Evidence |
|---|---|---|
| Overview dashboard | **Fully implemented** | `GET /fleet/analytics/overview` -- live snapshot, no stored trend |
| Device detail (capability/config/lifecycle views) | **Fully implemented, backend and frontend** | `/devices/{id}/capabilities`, `/config`, `/lifecycle-preview`, `/site`; frontend tabs for these were built this phase and independently verified via a clean `tsc`/`build`/`lint` pass (Section 13) |
| Health history | **Fully implemented (reused)** | `GET /devices/{id}/health-reports` (Phase 8, unchanged) |
| Alert generation + dedup | **Fully implemented** | `fleet_alert_service.evaluate_alerts_for_device()`, service-layer `dedup_key` upsert/auto-resolve, invoked inline on every health-report submission; `evaluate_alerts_for_all_devices()` additionally exposes an explicit `POST /fleet/alerts/evaluate-sweep` sweep so presence/stale alerts can be raised for a device that never reports at all |
| Version display | **Fully implemented (reused)** | `Device.software_version`/`protocol_version` (Phase 8, unchanged) |

### Tier 3 -- Administrative workflows

| Item | Status | Evidence |
|---|---|---|
| Extended lifecycle (`maintenance`/`decommissioned`) | **Fully implemented** | `_ADMIN_ALLOWED_TRANSITIONS`, `enter_maintenance()`, `decommission_device()`, both audited, decommission never deletes history |
| Lifecycle confirmation preview | **Fully implemented** | `preview_lifecycle_transition()`, `GET /devices/{id}/lifecycle-preview` -- read-only, no side effects |
| Capability discovery | **Fully implemented** | Five independent states per `(device, capability_key)`, device-reported vs. server-computed cleanly separated |
| Fleet sites/groups | **Fully implemented** | `FleetSite` reusing `GeoLocationMixin`, device assignment, per-site summary |
| Config-drift detection | **Fully implemented** | `fleet_config_service.compute_drift()`, missing baseline never reported as "no drift" |
| Audited alert acknowledge/resolve/reopen | **Fully implemented** | Full state machine, every human transition audited, analyst/admin-only (`INFRA_ALERT_MANAGE`) |

### Tier 4 -- Scale/hardening

| Item | Status | Evidence |
|---|---|---|
| Query optimization | **Partial** | Every new query is org-scoped and indexed on its lookup columns (`device_id`, `capability_key`, `dedup_key`, `site_id`); no query plan/EXPLAIN analysis or load test was performed against a large seeded fleet |
| Concurrency safety | **Implemented for config updates; not addressed elsewhere** | `fleet_config_service.update_config()`'s optimistic-concurrency `expected_revision` check is real and tested (`ConfigRevisionConflictError` -> HTTP 409); no equivalent concurrency guard was added for, e.g., two simultaneous lifecycle transitions on the same device (not identified as needed this phase, not specifically tested either) |
| Retention | **Not implemented -- explicitly deferred, unchanged from Phase 8** | No retention/purge job exists for `InfrastructureAlert`/`DeviceCapability`/`DeviceConfigBaseline` any more than it did for Phase 8's own `SyncRecord`/`SyncConflict`/`DeviceHealthReport` -- see `docs/operations/LOCAL_STORAGE_AND_RETENTION.md`'s still-accurate statement of this gap |
| Security + failure tests | **Implemented** | Viewer/Investigator permission-boundary tests on every new manage-level action, 404/409/400 failure-path tests across every new route file (`test_fleet_routes_additional_coverage.py`) |
| Docs | **Implemented** | This report plus the five other required documents, all listed in Section 9 below |

## Final Engineering Report

**1. Repository state before this phase's changes.** The real Phase
1-8 deliverable, unmodified at the start of this session's fleet work:
a backend with 718 passing tests at 93% coverage (Phase 8's own final
report), a frontend with the full Edge Operations surface, and accurate
`../PROJECT_STATUS.md`/`../MASTER_ROADMAP.md` handoff records explicitly
naming Phase 9 (fleet management and device observability) as the next
scope -- confirmed by reading both files, plus
`docs/architecture/EDGE_ARCHITECTURE.md`, before writing any code (per
`../PROJECT_STATUS.md`'s own Section 12 instruction to Phase 9).

**2. Components reused vs. newly introduced.** Reused, extended, never
duplicated: `Device.last_seen_at` (the sole input to presence
derivation -- no second heartbeat-tracking table), `Device.capabilities`/
`HealthReportRequest.runtime_capabilities`/`model_status` (Phase 8's
existing self-reported fields, the sole inputs to capability
discovery), `GeoLocationMixin` (Phase 7, reused verbatim for
`FleetSite` coordinates), `hash_password`/`verify_password` (untouched
-- no new credential logic was needed this phase), `audit_service.record()`
(called from every new state-changing function), and
`edge_sync_service.process_health_report()`'s existing ingestion path
(extended in place with two new calls -- capability sync and alert
evaluation -- rather than a second ingestion route). Newly introduced:
four primary-entity tables (`FleetSite`, `DeviceCapability`,
`DeviceConfigBaseline`, `InfrastructureAlert`); five new columns on
`devices`; seven new service modules; one new schema module; six new
route modules; five new `Permission`s; eleven new `Settings` fields.

**3. Files created or changed.** See `../PROJECT_STATUS.md` Section 5 for
the complete list. In summary -- Backend, new: 4 model files, 7 service
modules, 1 schema module, 6 route modules, 1 Alembic migration, 7 new
test files (66 new tests). Backend, modified: `app/models/device.py`
(+5 columns), `app/core/config.py` (+11 settings), `app/core/security.py`
(+5 permissions), `app/main.py` (+6 routers),
`app/services/edge_sync_service.py` (+2 inline calls in
`process_health_report()`), `app/services/device_service.py`
(+`enter_maintenance`/`decommission_device`/`preview_lifecycle_transition`
and the extended transition table), `app/schemas/device.py`
(+`presence_state`/`site_id`/config fields on `DeviceResponse`). Docs,
new: 6 files (this report plus the five listed in Section 9 below).
Docs, modified: `../MASTER_ROADMAP.md`, `README.md`,
`implementation/PROJECT_STATUS.md`.

**4. Database migration.** One new Alembic migration
(`3d7c5b9aa4e4_phase9_enterprise_fleet_management`): 4 new tables
(`fleet_sites`, `device_config_baselines`, `device_capabilities`,
`infrastructure_alerts`) and 5 new columns on the existing `devices`
table (`site_id`, `config_revision`, `config_baseline_id`,
`current_config`, `last_resource_metrics`). Hand-fixed after
autogeneration, the same discipline Phases 6 and 8's migrations
needed: safe server defaults (`server_default='0'`,
`server_default=sa.text("'{}'")`) were added for the two `NOT NULL`
columns with no default (`config_revision`, `current_config`), and the
two new foreign keys on the existing `devices` table required SQLite
batch-mode (`op.batch_alter_table`) since SQLite cannot `ALTER TABLE`
to add a foreign-key constraint directly. The migration's own
module docstring states this explicitly. Verified via the real
`alembic upgrade head` already applied to this session's working
`backend/aegis.db` (the full test suite runs against its own in-memory
SQLite fixtures, independent of this file, and passed cleanly
afterward -- see Section 8).

**5. Presence and heartbeats.** `fleet_presence_service.py` derives
`presence_state` purely from `Device.last_seen_at` -- the exact signal
every device-authenticated request (sync batch, health report,
heartbeat) already updates -- never a second, parallel tracking table.
`connectivity_state` (device-self-reported) and `presence_state`
(server-computed) are kept genuinely separate and never substitute for
each other, per the specification's own binding instruction. The heartbeat
endpoint (`POST /edge/presence/heartbeat`) is rate-limited
per-device by a documented best-effort, single-process, in-memory
limiter -- see Section 11 below and
`docs/security/DEVICE_LIFECYCLE_SECURITY.md` Section 6 for the full,
honest statement of its limitation.

**6. Health-finding rules.** `fleet_health_service.py` implements
three binding measurement-quality rules (missing data stays missing;
stale vs. fresh distinguished via `as_of`; device-reported vs.
server-computed distinguished via `source`) across five rules
(`presence_offline`/`presence_stale`/`disk_usage_high`/`battery_low`/
`sync_queue_backlog`), each with configurable `FLEET_HEALTH_*`
thresholds and self-contained `evidence`. Full detail:
`docs/architecture/DEVICE_HEALTH_MODEL.md`.

**7. Capability discovery.** `DeviceCapability` tracks five genuinely
independent states per `(device, capability_key)`:
`supported`/`installed`/`available_and_ready` (device-reported) and
`healthy`/`last_verified_at` (server-computed from the device's own
`model_status` health-report history, never fabricated from the
device-reported fields alone). `healthy=None` means never verified,
not unhealthy -- absence is never a negative finding. Full detail:
`docs/architecture/FLEET_MANAGEMENT.md` Section 4.

**8. Configuration baselines and drift.** `DeviceConfigBaseline` is an
append-only administrative-intent record; `fleet_config_service.compute_drift()`
only ever evaluates drift against an explicitly assigned baseline --
`evaluated=False`/`has_drift=None` when none is assigned (or it was
deleted), never a fabricated "no drift." Config updates use real
optimistic concurrency (`expected_revision` vs. `Device.config_revision`,
`ConfigRevisionConflictError` -> HTTP 409 on mismatch).

**9. Infrastructure alerts.** `InfrastructureAlert` is a dedicated
model/queue, deliberately separate from intelligence
`Event`s/`ObservationAnomaly`/`RiskAssessment` -- fleet-health alerting
only, never a sensed real-world condition. Deduplication is enforced in
the service layer via a stable `dedup_key` per ongoing condition
(repeated evaluation updates the existing open row; a resolved
condition's later recurrence creates a genuinely new row). Full
open/acknowledged/resolved/reopened lifecycle with complete audit on
every human transition. No real external notification is sent --
none is configured anywhere in this project. Alerts are
(re-)evaluated automatically on every health-report submission,
reusing Phase 8's existing ingestion path, never a second polling
system. Full detail: `docs/operations/INFRASTRUCTURE_ALERTS.md`.

**10. Administrative lifecycle extension.** `maintenance` (a
temporary, explicit, reversible pause, distinct from Phase 8's
`suspended`) and `decommissioned` (a permanent, explicit end-of-life
state reached before `revoked`, distinct from Phase 8's `revoked`)
were added with a full transition table and a read-only confirmation-
preview endpoint for every consequential transition. Decommissioning
never deletes historical sync/health/audit rows -- verified directly by
`test_decommission_preserves_historical_rows_and_blocks_reactivation`.
Full detail: `docs/security/DEVICE_LIFECYCLE_SECURITY.md`.

**11. Known limitation, repeated here deliberately.** The heartbeat
rate limiter is a documented, best-effort, single-process, in-memory
limiter -- not a distributed/multi-process-safe one, since this
project has no shared cache or broker of any kind. This is correct for
this project's actual single-process deployment model, and is stated
plainly as a known limitation in
`docs/security/DEVICE_LIFECYCLE_SECURITY.md` Section 6, not hidden.

**12. Permissions.** Five new `Permission` values: `FLEET_SITE_READ`/
`FLEET_SITE_MANAGE`, `INFRA_ALERT_READ`/`INFRA_ALERT_MANAGE`,
`FLEET_ANALYTICS_READ`. Administrator has all (implicit,
`set(Permission)`). Analyst has all five. Investigator has the three
`*_READ` permissions only -- deliberately **not** `FLEET_SITE_MANAGE`/
`INFRA_ALERT_MANAGE`, because fleet administration and alert
acknowledgment/resolution are fleet operations, not case-work (unlike
`EDGE_CONFLICT_MANAGE`, which Investigator does hold from Phase 8,
because resolving a sync conflict is case-work). Viewer has the three
`*_READ` permissions only. Device capability/config endpoints
deliberately reuse the existing `DEVICE_READ`/`DEVICE_MANAGE`
permissions rather than introducing new ones -- a deliberate reuse
decision, not an oversight, since these are just more facets of the
same `Device` resource Phase 8 already gated that way.

**13. Frontend.** `frontend/src/pages/fleet/` contains
`FleetOverviewPage.tsx`, `FleetSitesPage.tsx`, and
`FleetAlertCenterPage.tsx` (routed at `/fleet/overview`, `/fleet/sites`,
`/fleet/alerts`, with matching nav entries), plus extensions to
`EdgeDeviceListPage.tsx` (presence/site columns and filters) and
`EdgeDeviceDetailPage.tsx` (Capabilities tab, Configuration tab with
drift/baseline, a lifecycle-preview-then-confirm flow on all five
lifecycle actions, and site assignment) -- built concurrently by a
separate agent working on `frontend/` during this same phase, per this
phase's own instruction that this documentation effort stay out of
`frontend/` and `backend/app` entirely and work read-only against code,
write-only against `docs/` and the three root-status files. **The
frontend was independently verified this phase**, outside this
documentation effort itself: `npx tsc -b`, `npm run build`, and `npm
run lint`, run from `frontend/` directly, all passed cleanly (`tsc`:
no output; `build`: built successfully, only Vite's pre-existing
chunk-size informational note; `lint`: 0 errors, 2 pre-existing
warnings unrelated to this phase's work). This report does not claim
a live browser click-through or Playwright run was performed -- that
remains unverified.

**14. Testing.** 66 new backend tests across 7 new files, full suite
718 -> 784, all passing, 93% overall coverage maintained -- all
numbers re-measured fresh in this session
(`python -m pytest tests/ -q` and
`python -m pytest tests/ -q --cov=app --cov-report=term-missing`), not
assumed or copied from the phase's own scope description. A real bug
(a duplicate-row race inside `fleet_capability_service._get_or_create()`,
caused by this project's standing `autoflush=False` session
configuration) and a related SQLite timezone-round-trip issue were
both found and fixed during this testing process -- full detail in
`docs/testing/FLEET_TESTING.md` Section 3. Full test-file-by-file
breakdown: `docs/testing/FLEET_TESTING.md`.

**15. Explicit confirmation: no autonomous targeting, weapon control,
engagement decision, or remote-weapon code exists anywhere in this
phase's work.** Every model, service, route, and test introduced or
modified this phase concerns device inventory, presence/health
observability, capability inventory, configuration compliance,
fleet-health alerting, or administrative lifecycle state -- strictly
fleet observability/administration tooling, consistent with every
prior phase's own statement of this project's strictly defensive
scope. This was checked directly by reading every new file listed in
Section 3 before writing this report, the same discipline every prior
phase's final report has applied to itself.

**16. Known limitations, explicitly documented rather than silently
dropped.** The heartbeat rate limiter is single-process/best-effort
(Section 11). No retention/purge job exists for any new Phase 9 table,
any more than one existed for Phase 8's own tables (Tier 4 above). No
query-plan/load analysis was performed against a large seeded fleet.
Inline alert (re-)evaluation on a health-report submission alone can
never raise a `device_offline`/`device_stale` alert for a device that
has gone genuinely silent, since submitting a report is itself
evidence the device is online; this is now closed by the explicit
`POST /fleet/alerts/evaluate-sweep` operator/cron-triggered sweep
(`evaluate_alerts_for_all_devices()`), which evaluates every device
regardless of recent traffic (see
`docs/architecture/FLEET_MANAGEMENT.md` Section 7) -- there is still no
in-process background scheduler that calls it automatically, by
design. The `capability_unhealthy` alert type is reserved in
`INFRA_ALERT_TYPES` but has no current evaluator. No real external
notification channel exists anywhere in this project. The frontend
Fleet Operations Center was built this phase and independently
verified via a clean `tsc`/`build`/`lint` pass, though not via a live
browser click-through (Section 13). **Most
importantly: this entire phase -- every model, service, route, and
test described above -- builds on, and inherits, Phase 8's own
simulation-only status. No physical edge hardware was available in
this environment, and nothing in this report should be read as
implying real-hardware testing occurred at any point in this project.**

## Roadmap pointer

Phase 10 of 18 (**Explainable AI, Risk Analytics, Model Confidence,
Uncertainty Quantification, Human Review, and Decision Support**) is
next. Per this project's own standing discipline, Phase 10 should read
`docs/implementation/PROJECT_STATUS.md`,
`docs/implementation/MASTER_ROADMAP.md`'s Phase 10 preview, and this
report before writing any code, and should extend rather than duplicate
whatever model-confidence/risk-scoring scaffolding Phases 1-9 already
established (`RiskAssessment`, `ModelRecord`, `ModelEvaluationRun`) --
none of which this phase touched.
