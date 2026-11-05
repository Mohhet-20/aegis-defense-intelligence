# Offline Operations

**Status: IMPLEMENTED, tested in SIMULATION ONLY.** This document describes
operational behavior for a device that has lost, or never had, connectivity
to the central AEGIS backend, and for the recovery sweeps that handle a
process that crashed mid-sync. Everything here was exercised against
`app/edge/simulator.py`'s `SimulatedEdgeNode`, never real edge hardware --
see `docs/architecture/EDGE_ARCHITECTURE.md` Section 18.

## 1. What "offline" means for a device

`SimulatedEdgeNode.go_offline()`/`go_online()` model genuine lost
connectivity: while offline, `flush_once()` never even attempts a network
call (not a faked exception) -- it returns
`{"attempted": False, "reason": "offline"}` immediately, exactly like a
device with no signal. A device's `connectivity_state`
(`online`/`offline`/`unknown`) is self-reported through `POST /edge/sync/health`
and is advisory, display-only information for an operator -- it is never
used to gate whether a sync batch is accepted; `require_device_auth` and
`administrative_status` are the only gates on that.

## 2. The local outbox while offline

Every call to `SimulatedEdgeNode.capture()` enqueues a record into
`LocalEdgeStore` immediately and durably, regardless of current
connectivity -- capture and connectivity are completely decoupled. A device
can capture an arbitrary number of records (bounded only by local storage,
which this layer does not itself cap -- see
`docs/operations/LOCAL_STORAGE_AND_RETENTION.md`) while offline, and nothing
is lost: durability was proven by closing and reopening the same SQLite
file. `LocalEdgeStore.stats()`'s `queue_depth`/`pending_sync_count` give the
device's own honest view of how much is backed up locally.

## 3. Reconnect and backlog flush

On reconnect (`go_online()`), nothing flushes automatically inside this
layer's model -- a caller invokes `flush_once()` (one batch) or
`run_until_drained()` (repeated `flush_once()` calls, bounded by
`max_cycles`, default 20, until the local queue is empty or an attempt
doesn't even get attempted). Each `flush_once()` call:

1. Pulls up to `batch_size` (default 20) rows via
   `LocalEdgeStore.list_ready_to_send()` -- freshly `queued`, or
   `retryable_failure` whose backoff window (`next_retry_at`) has elapsed,
   oldest-`queued_at`-first.
2. Marks each row `syncing` locally (generating a fresh `message_id` for
   this attempt).
3. Sends one real `POST /api/v1/edge/sync/batch` HTTP request.
4. Classifies the response and applies the verdict back to the local row
   via `apply_ack()`/`mark_network_failure()`/`mark_auth_failure()` --
   the local store never second-guesses the server's classification, it
   mirrors whatever `sync_status` the ack carried.

A device resuming after being offline for a long time sends its oldest
backlog first, in `queued_at` order, never newest-first and never an
unbounded single request (capped by `batch_size`/`EDGE_SYNC_MAX_BATCH_SIZE`).

## 4. Crash recovery -- both sides, both manual

Two independent, separately-tested sweeps:

- **Edge side:** `LocalEdgeStore.recover_crashed(stale_after_seconds=...)`
  resets a local row stuck in `syncing` (the process died before learning
  whether the server received the request) back to `retryable_failure`. The
  idempotency key guarantees the central side treats the eventual resend as
  a no-op if the original request had actually succeeded server-side.
- **Central side:** `edge_sync_service.recover_stale_syncing_records()`
  resets a `SyncRecord` stuck in `syncing` for longer than
  `EDGE_SYNC_SYNCING_STALE_AFTER_SECONDS` (300s) to
  `retryable_failure`/`permanent_failure`.

**Neither sweep runs on a timer.** There is no background scheduler
anywhere in this project -- every component so far is
request/response only. The central sweep is exposed as an explicit API
endpoint, `POST /api/v1/edge/sync/recover-stale` (`EDGE_SYNC_MANAGE`),
meant to be triggered by an operator or an external cron hitting the API.
The edge-side sweep is a method a real device's own startup code would call
once, before resuming normal operation. **Operational implication:** if a
central worker process genuinely crashes mid-request, its in-flight
`SyncRecord`s sit in `syncing` indefinitely until something calls
`recover-stale` -- an operator running this in production should wire that
endpoint to an external cron (e.g. every few minutes), since nothing inside
this codebase will call it on its own.

## 5. The synchronous-architecture operational implication

Because every batch request resolves synchronously within its own
request/response cycle (see
`docs/architecture/EDGE_ARCHITECTURE.md` Section 8), `pending_sync_count` on
the device list and in the queue summary stays near-zero during normal
operation -- there is no "staged, waiting to be processed" population of
records the way a queue-backed architecture would show. An operator should
expect to see a non-trivial pending count only when:

- a device has a genuinely large **local** backlog it hasn't yet sent (this
  is real and durable, but invisible to the central system until the device
  actually flushes it), or
- a `retryable_failure` backoff window is actively in progress for one or
  more records, or
- the crash-recovery sweep hasn't yet been run against a backlog of
  records stuck in `syncing` from a crashed process.

A dashboard that always shows `pending_sync_count ≈ 0` is not necessarily
broken -- see `docs/operations/EDGE_TROUBLESHOOTING.md` for the
operator-facing version of this same point.

## 6. Known gaps

- No automatic flush-on-reconnect trigger exists -- a real
  device integration would need to call `flush_once()`/`run_until_drained()`
  itself on a timer or on a connectivity-change callback; nothing in
  `app/edge/` does this automatically.
- No automatic retention/purge of old local outbox rows -- see
  `docs/operations/LOCAL_STORAGE_AND_RETENTION.md`.
- Simulation only -- no real intermittent-connectivity network path has
  been exercised.
