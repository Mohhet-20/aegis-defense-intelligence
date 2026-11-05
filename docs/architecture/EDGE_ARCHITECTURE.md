# Edge AI, Offline-First Operation, and Synchronization Architecture

**Status: IMPLEMENTED, tested, and live-verified in SIMULATION ONLY.** No
physical edge hardware is available in this environment -- see Section 18.
This document supersedes `docs/architecture/EDGE_SYNC_CONTRACTS.md`'s
`PLANNED` sketch for everything actually built here; that file is left
unmodified as the historical record, consistent with how the other layers
treated their own superseded contract sketches.

## 1. Scope and non-scope, stated first

Delivers: device identity and lifecycle, local (simulated) offline
persistence, local (synthetic) AI inference, a durable idempotent sync
protocol, a two-tier conflict policy, and an admin-facing Edge Operations
surface (API + frontend). It does **not** deliver real edge hardware
integration, a device fleet dashboard beyond what this layer needs for its
own sync/conflict review (that is the "Fleet Management and Device
Observability"), or automatic promotion of synced data into canonical
`Event`/`Observation`/`Evidence` rows (Section 7 below). Strictly defensive
scope, confirmed clean: no autonomous targeting, weapon
control, engagement logic, or remote weapon interface exists anywhere in
`app/edge/`, the device/sync models, or the new routes -- the one edge
inference adapter is a synthetic brightness classifier, nothing resembling a
weapons system.

## 2. Components and how they fit together

| Component | Where | Role |
|---|---|---|
| Device identity and registry | `app/models/device.py`, `app/services/device_service.py` | Who a device is, what it's allowed to do, its lifecycle. |
| Local persistence (simulated edge side) | `app/edge/local_store.py` (`LocalEdgeStore`) | The device's own durable outbox -- raw `sqlite3`, its own `.db` file. |
| Local capture + AI inference (simulated edge side) | `app/edge/simulator.py` (`SimulatedEdgeNode`), `app/edge/inference/registry.py` | Produces logical records and (optionally) synthetic inference results to enqueue. |
| Durable outbound sync (simulated edge side) | `SimulatedEdgeNode.flush_once()`/`run_until_drained()` | Sends queued records over real HTTP, classifies the response, drives local retry. |
| Durable inbound sync (central) | `app/services/edge_sync_service.py`, `app/models/sync_record.py` | The authoritative server-side state machine for every sync attempt ever made. |
| Conflict detection/resolution (central) | `app/models/sync_conflict.py`, `app/services/edge_conflict_service.py` | Revision-mismatch detection for the one mutable record type, and its human-resolved review queue. |
| Sync monitoring (central) | `app/api/routes/edge_sync_admin.py`, `SyncQueueSummaryResponse` | Queue summary, record list/detail, retry/cancel, manual crash-recovery trigger. |
| Security/audit | `app/core/security.py` (`require_device_auth`, 6 new `Permission`s), `audit_service` calls throughout | Device-credential auth, RBAC, and an audit record for every state-changing action. |
| Frontend (Edge Operations) | `frontend/src/pages/edge/*` | Device registry/detail, sync queue, conflict review. |

Reused, not duplicated: `Device` (a real registry + lifecycle + credential
record currently, extending the placeholder shape rather
than replacing it), `hash_password`/`verify_password` (the same bcrypt
functions user passwords already use -- a device secret is just another
secret, no second hashing scheme invented), `audit_service.record()` (every
new state-changing function calls it, same pattern as every earlier work),
and the existing `Page[...]`/`require_permission` plumbing for every new
admin route. Newly introduced: `SyncRecord`/`SyncConflict`/
`DeviceHealthReport` models, the `app/edge/` simulated-runtime package, and
`app/schemas/edge_sync.py`'s versioned protocol envelope.

## 3. Device identity and lifecycle

`Device.device_identifier` is a stable, human-chosen string (e.g.
`edge-fob-alpha-01`), deliberately **globally unique across the whole
platform, not just per-organization** -- the device-auth lookup
(`device_service.get_device_by_global_identifier()`) needs to find a device
before it knows which organization that device belongs to, the same way the
JWT login flow looks a user up by email alone. `administrative_status`
(`pending` -> `active` -> `suspended`/`revoked`) is enforced by
`device_service.transition_administrative_status()`'s own allowed-transition
table: `pending` is the only start state (enrollment never silently grants
unrestricted access -- a `pending` device cannot authenticate a single
request), and `revoked` is terminal (a revoked device is re-enrolled as a
brand-new row, never resurrected). `connectivity_state`
(online/offline/unknown) and `capabilities`/`inference_backends`/
`model_manifest` are self-reported and advisory only -- never used for
authorization, which is permission + `administrative_status` alone. Full
detail: `docs/security/EDGE_DEVICE_SECURITY.md`.

## 4. Local (simulated) persistence and capture

`app/edge/local_store.py`'s `LocalEdgeStore` is a genuinely separate SQLite
database file, opened with raw `sqlite3` against its own `.db` path --
deliberately never the central app's SQLAlchemy session/engine, so "local
vs. central ownership" is a real architectural boundary a test can actually
exercise (close the connection, reopen the same file, prove nothing was
lost), not just a documented intention. It reuses
`app.models.sync_record.SYNC_RECORD_TRANSITIONS` verbatim for its own local
state machine -- Section 6 of the original spec describes one documented
state machine, and this is deliberately the same one, enforced the same way,
on both ends of the protocol. `SimulatedEdgeNode.capture()` enqueues a
logical record immediately and durably, regardless of current connectivity.

## 5. Local AI inference (simulated)

`app/edge/inference/registry.py` is a closed adapter allow-list -- the same
pattern as `app/sensors/adapters/registry.py` and `app/connectors/registry.py`
-- with exactly one registered adapter, `DeterministicSyntheticAdapter`. See
`docs/architecture/EDGE_INFERENCE.md` for the full detail; the one point
worth repeating here is that `run_inference()` returns a plain result dict,
**never** a `SyncRecord` -- inference results are explicitly kept separate
from synchronization state. If a result needs to be synced centrally, it is
submitted as an ordinary `inference_output` record through the normal sync
path, same as any other capture.

## 6. Durable outbound and inbound sync

`SimulatedEdgeNode.flush_once()` sends a bounded batch (`batch_size`,
default 20) of ready-to-send local rows over real HTTP to
`POST /api/v1/edge/sync/batch`, classifying the response exactly as a real
device would: a connection-level error or 5xx is retried with locally
computed backoff; a 429 respects the server's `Retry-After` header; a
401/403 is **never** retried (the credential itself is the problem, not a
transient condition). On the central side, `edge_sync_service.process_record()`
is the only place that ever writes `SyncRecord.sync_status`, and every
transition goes through `_transition()`, which enforces
`SYNC_RECORD_TRANSITIONS` -- an illegal transition raises
`InvalidSyncTransitionError`, never silently allowed. Full protocol detail:
`docs/architecture/SYNC_PROTOCOL.md`. Full conflict-policy detail:
`docs/operations/CONFLICT_RESOLUTION.md`.

## 7. Why an accepted SyncRecord is not auto-promoted to a domain row

`SyncRecord` is itself the durable, auditable, queryable record of what an
edge device sent and the central system durably accepted. It is
**deliberately not** automatically materialized into a canonical `Event`,
`Observation`, or `Evidence` row the moment it reaches `synced`. Promoting
it into a first-class domain row is a reasonable, explicitly deferred
Follow-up (stated in `app/models/sync_record.py`'s own module
docstring), not a silent gap:
doing that promotion correctly needs the record-type-specific validation,
deduplication, and provenance rules each target table already has from
the earlier layers, and conflating that work into this layer's sync-protocol scope
would have meant half-building both.

## 8. The honest synchronous-acceptance characteristic

**This backend's sync acceptance is fully synchronous per HTTP request.**
Every record submitted in a batch resolves to `synced`, `conflict`, or
`quarantined` within the same request/response cycle --
`edge_sync_service.process_record()` runs `_accept_record()` inline, commits,
and returns the result in the same call that handled the HTTP request. There
is no background worker, no message queue, and no staging area between
`SyncRecord` and "truly durable" -- the `SyncRecord` table **is** the durable
central store, not a staging area for one.

`retryable_failure` on the central side only occurs if a genuine database
error happens during that single request (exercised in unit tests via
fault-injection -- monkeypatching a DB commit to raise once). It was **not**
reliably triggerable under real concurrent load during this session's live
verification, because there is no downstream dependency for it
to fail against. This is correct, honest behavior given the architecture,
not a bug -- but it has a real operational consequence worth stating
plainly: **`pending_sync_count` on the device list stays near-zero under
normal operation.** An operator who expects to see a large "queued" number
whenever a device is online will not see one unless genuinely many devices
are offline with real local backlogs (a device's own un-flushed local
outbox, `app/edge/local_store.py`, is real and durable, but is invisible
server-side until the device actually sends it -- that invisibility is
itself correct, not a bug). See also
`docs/operations/OFFLINE_OPERATIONS.md` and
`docs/operations/EDGE_TROUBLESHOOTING.md`.

## 9. Crash recovery

Two independent sweeps exist, one per side of the protocol:

- Central: `edge_sync_service.recover_stale_syncing_records()` resets a
  `SyncRecord` left in `syncing` for longer than
  `EDGE_SYNC_SYNCING_STALE_AFTER_SECONDS` (300s default) to
  `retryable_failure`/`permanent_failure`, exactly as if its acceptance had
  raised. Exposed as `POST /api/v1/edge/sync/recover-stale`
  (`EDGE_SYNC_MANAGE`).
- Edge (simulated): `LocalEdgeStore.recover_crashed()` does the identical
  thing to local outbox rows stuck in `syncing`.

**There is no background scheduler anywhere in this project** -- every component
so far is request/response only. Both sweeps are meant
to be triggered by an operator or an external cron hitting the API, never an
automatic in-process timer. State this plainly to anyone operating a real
deployment: a device or a central process that genuinely crashed mid-sync
stays in `syncing` until something calls the recovery endpoint/function.

## 10. Permissions

Six new `Permission` values (`app/core/security.py`): `DEVICE_READ`,
`DEVICE_MANAGE`, `EDGE_SYNC_READ`, `EDGE_SYNC_MANAGE`, `EDGE_CONFLICT_READ`,
`EDGE_CONFLICT_MANAGE`. Administrator has all (implicit, `set(Permission)`).
Analyst has all six. Investigator has `DEVICE_READ` + `EDGE_SYNC_READ` +
`EDGE_CONFLICT_READ` + `EDGE_CONFLICT_MANAGE` only -- deliberately **can**
resolve conflicts (reviewing/resolving conflicting field data is case-work,
the same category as `EVIDENCE_MANAGE`) but **cannot** register/revoke
devices or force-retry/cancel sync records, which is fleet administration.
Viewer has the three `*_READ` permissions only. Full matrix and rationale:
`docs/operations/CONFLICT_RESOLUTION.md` and
`docs/security/EDGE_DEVICE_SECURITY.md`.

## 11. Configuration

All new settings live in `app/core/config.py` with safe defaults:
`EDGE_SYNC_MAX_BATCH_SIZE` (100), `EDGE_SYNC_RETRY_BASE_DELAY_SECONDS` (5.0),
`EDGE_SYNC_RETRY_MAX_DELAY_SECONDS` (3600.0),
`EDGE_SYNC_RETRY_JITTER_FRACTION` (0.2), `EDGE_SYNC_MAX_RETRY_COUNT` (10),
`EDGE_SYNC_SYNCING_STALE_AFTER_SECONDS` (300.0),
`EDGE_DEVICE_HEALTH_REPORT_MAX_RESULTS` (200), `EDGE_SYNC_MAX_PAYLOAD_BYTES`
(262144, i.e. 256KB).

## 12. API surface

Four route files, all mounted under `/api/v1`: `edge_devices.py` (JWT admin,
prefix `/devices`: register, list, get, activate, suspend, revoke,
rotate-key, health-reports, status-history), `edge_sync.py` (device-auth,
prefix `/edge/sync`: `POST /batch`, `POST /health`), `edge_sync_admin.py`
(JWT admin, same `/edge/sync` prefix: list/get/retry/cancel sync records,
queue summary, manual `recover-stale` trigger), `edge_conflicts.py` (JWT
admin, prefix `/edge/conflicts`: list/get/resolve).

## 13. Frontend

`frontend/src/pages/edge/`: `EdgeDeviceListPage.tsx`,
`EdgeDeviceDetailPage.tsx` (Overview/Sync Activity/Health History/Audit
Trail tabs), `EdgeSyncQueuePage.tsx`, `EdgeConflictReviewPage.tsx`,
`EdgeConflictDetailPage.tsx` (side-by-side `local_version`/`central_version`
JSON comparison). New reusable primitives in
`frontend/src/components/ui/Primitives.tsx`: `Tabs`, `Modal`,
`OneTimeSecretField` (for displaying a plaintext device API key exactly
once, copyable, never re-shown). Routes: `/edge/devices`,
`/edge/devices/:deviceId`, `/edge/sync`, `/edge/conflicts`,
`/edge/conflicts/:conflictId`. Nav entries: "Edge Devices", "Sync Queue",
"Edge Conflict Review".

## 14. Database migration

One Alembic migration, `f7c55967f675_edge_sync_offline_operation`,
verified via a full upgrade/downgrade/upgrade round trip against a
throwaway DB before being applied to the real dev DB. See
`docs/operations/EDGE_TROUBLESHOOTING.md` for the two SQLite-specific fixes
it needed.

## 15. Testing

98 new backend tests across 9 new files, full suite 620 -> 718, all passing,
93% overall coverage maintained. Also live-verified end-to-end this session
against real running servers. Full detail: `docs/testing/EDGE_TESTING.md`.

## 16. Known gaps, stated honestly (not hidden)

- An accepted `SyncRecord` is not auto-promoted to a domain row (Section 7).
- The device registration form's `model_manifest` is always submitted as
  `{}` (no rich JSON editor yet); `capabilities`/`inference_backends` are
  plain comma-separated text inputs on the frontend.
- No background scheduler exists anywhere in this project -- crash-recovery
  sweeps are manually/externally triggered via API (Section 9).
- No automatic retention/purge job for `SyncRecord`/`SyncConflict`/
  `DeviceHealthReport`/the local outbox -- see
  `docs/operations/LOCAL_STORAGE_AND_RETENTION.md`.
- `retryable_failure` on the central side is real and tested but not
  reliably reproducible under its own live load (Section 8).

## 17. What this project explicitly does NOT build (reserved for later work)

- Any autonomous targeting, weapon control, engagement decision, or remote
  weapon interface -- not part of this project's scope at any point.
- Real fleet observability/dashboards beyond its own device
  registry and sync/conflict queues -- that is the "Enterprise Edge
  Fleet Management, Device Observability, Health Monitoring, Capability
  Inventory, Lifecycle Management, Operational Dashboards."
- A second, trained edge-inference adapter -- see
  `docs/architecture/EDGE_INFERENCE.md`.
- Any coordinate/location handling beyond what a captured record's own
  `payload` carries -- if later work needs a device's own location,
  the design is to reuse the `GeoLocationMixin`/`app/geo/`, not add
  parallel location-handling logic.

## 18. Simulation-only honesty statement

**This edge runtime has only ever run in simulation.** No physical edge
hardware is available in this development environment. `app/edge/__init__.py`
states this directly, and it is restated here because it is the single most
important caveat on everything else in this document:
`SimulatedEdgeNode` makes real HTTP calls (via `httpx`) to the real FastAPI
application -- either a live `uvicorn` server or an in-process ASGI
transport in tests -- and classifies responses exactly as a real device
would, but nothing in this codebase has executed on, or been validated
against, actual edge device hardware, a real cellular/radio link, or a real
intermittent-connectivity network path.
