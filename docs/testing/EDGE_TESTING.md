# Edge Testing

**Status: IMPLEMENTED.** 98 new backend tests across 9 new files. Full
backend suite: **718 passed** (620 carried forward +
98 new this layer), 0 failed, **93% overall line coverage maintained**.
Plus a separate, manually-run live end-to-end verification pass against
real servers -- distinguished explicitly from the automated suite below.

## 1. Backend test files, by layer

**Service layer, real SQLite-backed `Session` fixtures:**

- `tests/test_device_service.py` (12 tests) -- registration issuing a
  one-time key in `pending` status, global-identifier duplicate rejection,
  a `pending` device failing authentication, an `active` device
  authenticating and updating `last_seen_at`, wrong-key rejection,
  suspend/reactivate, revoke being terminal and invalidating the
  credential, `pending` being unable to skip straight to `suspended`, key
  rotation invalidating the old key, rotation being rejected on a revoked
  device, the live-computed `pending_sync_count` actually reflecting the
  real queue, and the lifecycle audit trail (status-history).
- `tests/test_edge_local_store.py` (13 tests) -- enqueue persisting
  `queued`, idempotency-key uniqueness, a fresh `message_id` on every
  `mark_syncing()` attempt, `synced` being terminal, `retryable_failure`
  computing backoff from a server-supplied `Retry-After`, network-failure
  classification/backoff, auth-failure being permanent and never
  auto-retried, `cancel()`'s legal-state restriction,
  `list_ready_to_send()` correctly excluding `syncing` rows and rows still
  inside their backoff window, `recover_crashed()` resetting truly stale
  rows and correctly ignoring fresh ones, status-count stats, and **the
  core durability proof**: data surviving the same DB file being closed
  and reopened.
- `tests/test_edge_sync_service.py` (24 tests) -- the largest file,
  covering: new-immutable-record acceptance, idempotent resubmission (same
  key = no-op), same-`client_record_id`-same-hash idempotency vs.
  different-hash quarantine, unknown-`record_type` and oversized-payload
  quarantine, mutable-record `base_revision` requirement, a matching
  `base_revision` succeeding, a stale `base_revision` creating a conflict
  **and never overwriting**, a correct second edit succeeding, whole-batch
  rejection on an unsupported protocol version, batch-too-large rejection,
  the transition table rejecting an illegal transition, every documented
  state appearing in the transition table, `compute_backoff_seconds()`
  being bounded and deterministic with jitter disabled, a genuine
  fault-injected transient server error during acceptance being retried
  with backoff, a `retryable_failure` record reprocessing and succeeding
  on resubmission, exceeding max retry count moving to
  `permanent_failure`, cancel being rejected once `synced` but succeeding
  while `queued`, force-retry resetting retry count from
  `permanent_failure`, force-retry being rejected on an already-`synced`
  record, the crash-recovery sweep touching only truly stale rows, and the
  queue summary reflecting real counts.
- `tests/test_edge_conflict_service.py` (7 tests) -- `keep_central`
  discarding the device's submission, `keep_local` promoting it,
  `merged` **never taking the device's payload verbatim**, rejecting a
  second resolution of an already-resolved conflict, rejecting an invalid
  `resolution_strategy`, confirming the resolution is fully audited, and
  resolution-status filtering on the list query.
- `tests/test_edge_inference_registry.py` (6 tests) -- the closed
  allow-list being reported correctly, an unknown adapter raising,
  deterministic output, the below-threshold "dim" branch, full provenance
  on the result dict, and rejection of an unavailable adapter.

**API layer, real FastAPI `TestClient`:**

- `tests/test_edge_devices_api.py` (11 tests) -- `DEVICE_MANAGE` required
  to register, Viewer forbidden, Investigator can read but not manage,
  duplicate identifier returns 409, a full lifecycle walked through the
  real API, key rotation actually invalidating the old key end-to-end,
  administrative-status filtering on list, 404 on an unknown device, 400
  on an illegal lifecycle transition, 400 rotating a revoked device's key,
  and the health-report-history endpoint.
- `tests/test_edge_sync_api.py` (13 tests) -- missing device headers
  rejected, a real batch accepted and synced, spoofed `device_id`
  rejected, unsupported protocol version rejected, health report
  requiring device auth, admin listing sync records, Viewer forbidden
  from force-retry/cancel, Analyst able to cancel a `queued` record but
  not a `synced` one, the queue-summary endpoint, `recover-stale`
  requiring `EDGE_SYNC_MANAGE`, 404 on an unknown sync record, 413 on an
  oversized batch, and 400 on an unsupported-version health report.
- `tests/test_edge_conflicts_api.py` (6 tests) -- list/get, Viewer
  forbidden from resolving, Investigator **can** resolve (confirming the
  deliberate permission split -- see
  `docs/operations/CONFLICT_RESOLUTION.md`), 400 on an invalid strategy,
  400 on resolving twice, 404 on an unknown conflict.
- `tests/test_edge_simulator.py` (6 tests) -- capture-and-flush actually
  syncing through the real API (via an in-process ASGI transport, not a
  direct service call), offline capture never being sent until
  reconnect, a health report round-tripping through the real API, a
  mutable-record conflict being genuinely visible through real sync
  traffic, a genuine network failure being classified and backed off, and
  the local store surviving a simulated process restart mid-backlog.

## 2. Coverage, by module (new code)

| Module | Line coverage |
|---|---|
| `app/services/edge_sync_service.py` | 96% |
| `app/services/device_service.py` | 95% |
| `app/services/edge_conflict_service.py` | 96% |
| `app/edge/local_store.py` | 96% |
| `app/edge/simulator.py` | 79% |
| `app/edge/inference/registry.py` | 100% |
| New route files (`edge_devices.py`, `edge_sync.py`, `edge_sync_admin.py`, `edge_conflicts.py`) | 83-100% |

**Overall project coverage stayed at 93%** across the full suite --
adding this layer's roughly 3,100 lines of new backend code did not
regress the project's existing coverage bar. `simulator.py`'s lower
figure (79%) is mostly its constructor branch for an injected vs.
self-owned `httpx.Client` and a couple of less-common HTTP-status
branches (`429`, generic non-200/non-5xx) that the automated suite
exercises less exhaustively than the core accept/conflict/quarantine
paths -- the manual live-verification pass below separately exercised
real `synced`, `conflict`, and `quarantined` traffic through this same
module.

## 3. Automated suite vs. manual live verification -- kept distinct

**Automated (`pytest`), re-run fresh this session, not assumed from an
earlier run:** 718 passed, 0 failed, 93% coverage. This is entirely
in-process -- SQLite fixtures for the service/API tests, and an
in-process ASGI transport (`httpx.ASGITransport(app=app)`) for
`test_edge_simulator.py` -- no real network socket, no real `uvicorn`
process, in any automated test.

**Manual live verification, also actually performed this session, using
real running processes:**

- Real `uvicorn` (backend) and `vite` (frontend) dev servers were
  started against the real re-seeded dev database.
- A real `SimulatedEdgeNode` made real HTTP calls (not injected, not an
  ASGI transport) against the live running server, over an actual TCP
  socket to `localhost`.
- This produced genuine `synced` records, a genuine cross-device
  `annotation` conflict (created by two simulated devices submitting
  overlapping revisions), and a genuine `quarantined` integrity-failure
  record (a resubmission of the same `client_record_id` with a different
  payload).
- The cross-device conflict was resolved **end-to-end through the real
  frontend UI** (the Edge Conflict Review workspace), then verified via
  the API afterward to confirm the resolution actually took effect
  server-side.
- Playwright screenshots were taken of every new frontend page/tab
  (device list/detail with all four tabs, sync queue, conflict review,
  conflict detail) and visually reviewed, confirming real data rendering
  correctly -- not an empty or broken state.

These two verification passes are **not interchangeable**: the automated
suite proves the logic is correct under controlled, repeatable
conditions; the live pass proves the same logic actually works when
driven through a real HTTP stack, a real browser, and real user
interaction, which is the bar this project has held.

## 4. Known gaps's testing

- No load/concurrency test exercises many devices syncing simultaneously
  against a shared SQLite file -- the fault-injection test for
  `retryable_failure` is the only place a concurrent-write-style failure
  is exercised, and it's via monkeypatching, not real concurrent load
  (see `docs/architecture/EDGE_ARCHITECTURE.md` Section 8 for why real
  concurrent load didn't reliably reproduce it here).
- No test exercises the local outbox growing to a large number of rows
  (retention/performance at scale is an explicitly stated gap, not a
  tested-and-passed property -- see
  `docs/operations/LOCAL_STORAGE_AND_RETENTION.md`).
- This entire test suite, automated and manual alike, runs against the
  simulated edge runtime only -- no physical-hardware test exists or
  could exist in this environment.
