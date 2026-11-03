# Edge Troubleshooting (Phase 8)

**Status: IMPLEMENTED.** Common issues an operator or developer may hit
with edge device registration, sync, and conflict resolution, and their
real causes -- written from what was actually observed exercising this
phase, not speculative.

## Device can't authenticate

**Symptom:** `POST /edge/sync/batch` or `POST /edge/sync/health` returns
401/403.

**Real causes, in order of likelihood:**

1. `administrative_status` is not `active`. `authenticate_device()`
   rejects `pending` (not yet activated by an operator -- call
   `POST /devices/{device_id}/activate`), `suspended` (temporarily
   disabled), and `revoked` (permanently disabled, `api_key_hash` already
   cleared) equally -- check `GET /devices/{device_id}` for the current
   status.
2. The API key was rotated or the device was revoked since the key was
   last read -- `rotate_api_key()`/revocation both invalidate the old
   hash immediately; the device needs its newest plaintext key, which can
   only be read back at the moment of rotation (it is never stored
   recoverably -- see `docs/security/EDGE_DEVICE_SECURITY.md`).
3. Wrong header names -- the scheme is `X-Device-Id`/`X-Device-Api-Key`,
   not an `Authorization: Bearer` JWT. A device credential will never work
   against a JWT-protected route and vice versa.

## Batch rejected with HTTP 400

**Real causes:**

- **`device_id` mismatch.** The batch body's `device_id` must equal the
  authenticated device's own `device_identifier` exactly -- this is the
  deliberate anti-spoofing check in `edge_sync.py`'s route handler. Fix:
  make sure the device is sending its own identifier, not a stale/copied
  one from another device's configuration.
- **Unsupported `protocol_version`.** Only `"edge_sync_v1"` is accepted
  (`SUPPORTED_EDGE_SYNC_PROTOCOL_VERSIONS`). This rejects the **whole
  batch** -- individual records are never partially processed under an
  unsupported version. Fix: upgrade the device's sync client, or confirm
  it isn't sending a stale hardcoded version string.
- **Batch too large.** More than `EDGE_SYNC_MAX_BATCH_SIZE` (100, by
  default) records in one request raises `BatchTooLargeError`. Fix: send
  smaller batches (`SimulatedEdgeNode.flush_once(batch_size=...)`'s
  default is already 20).

## A record is `quarantined`

**Real cause:** `error_category = "integrity_failure"` almost always means
the device resubmitted the **same** `client_record_id` with a
**different** `payload_hash` than what was already accepted under that id
-- `_accept_immutable()`'s deliberate policy. This is **never
auto-resolved** -- it needs a human decision (was the original payload
wrong? is this a genuinely different logical record that reused an id by
mistake?). There is currently no dedicated "un-quarantine" workflow beyond
moving the record to `permanent_failure`; a corrected version of the
record should be resubmitted under a new `client_record_id` if that's the
right fix. A `validation_error`-category quarantine instead means an
unknown `record_type`, an oversized payload
(`EDGE_SYNC_MAX_PAYLOAD_BYTES`), or a mutable-type submission missing
`base_revision` -- check `last_error_message` for the specific reason.

## A conflict sits unresolved

**Real cause:** every `SyncConflict` requires an explicit human resolution
through `POST /edge/conflicts/{conflict_id}/resolve` -- nothing in this
codebase auto-resolves a conflict, by design (see
`docs/operations/CONFLICT_RESOLUTION.md`). If a conflict queue is growing,
check that whoever has `EDGE_CONFLICT_MANAGE` (Administrator, Analyst, or
Investigator) is actually reviewing it -- there is no SLA/escalation
mechanism, since no background scheduler exists in this project at all.

## Why is `pending_sync_count` always (or almost always) 0?

**Not a bug.** This backend's sync acceptance is fully synchronous per
HTTP request -- every record resolves to `synced`/`conflict`/`quarantined`
within the same request/response cycle that submitted it. There is no
queue-backed staging area for `pending_sync_count` to reflect; the
`SyncRecord` table itself is the durable store. A non-zero
`pending_sync_count` means one of: a device has a real, un-flushed local
backlog it hasn't sent yet (invisible server-side until it does); a
`retryable_failure` record is actively waiting out its backoff window; or
a crash-recovery sweep hasn't yet run against records stuck in `syncing`
from a crashed process. See
`docs/architecture/EDGE_ARCHITECTURE.md` Section 8 and
`docs/operations/OFFLINE_OPERATIONS.md` Section 5 for the full explanation.
Do not interpret a near-zero count as evidence the sync pipeline is idle or
broken -- it is the expected steady state.

## The SQLite migration gotcha (for anyone re-running or adapting this migration)

Migration `f7c55967f675_phase8_edge_sync_offline_operation` needed two
SQLite-specific fixes, both already applied in the committed migration:

1. **`batch_alter_table` for a new foreign key on an existing table.**
   SQLite cannot `ALTER TABLE ... ADD CONSTRAINT` a foreign key directly;
   adding `devices.registered_by_user_id`'s FK to `users` required
   wrapping the constraint creation (and its downgrade-path drop) in
   `with op.batch_alter_table('devices') as batch_op: ...`, which
   recreates the table under the hood the way SQLite's `ALTER TABLE`
   limitations require.
2. **Explicit `server_default` on every new `NOT NULL` column.** Every
   `NOT NULL` column added to the pre-existing `devices` table (e.g.
   `device_identifier`, `connectivity_state`, `administrative_status`,
   the JSON `capabilities`/`inference_backends`/`model_manifest` columns)
   needed an explicit `server_default` so the `ALTER TABLE ADD COLUMN`
   succeeds against any existing rows -- without one, SQLite (and most
   other backends) rejects adding a `NOT NULL` column with no default to
   a table that might already have rows.

The migration was verified with a full upgrade/downgrade/upgrade round
trip against a throwaway database before being applied to the real dev
database -- not merely written and assumed correct.

## Other things that are not bugs

- A device's `sync_status` convenience column
  (`never_synced`/`synced`/`pending`/`conflict`) can lag the true
  live-computed state briefly between requests -- it is recomputed on
  every `ingest_batch()` call but is explicitly documented as a
  last-known value, not an authoritative one (`device_service.compute_pending_sync_count()`/
  `compute_unresolved_conflict_count()` are the authoritative live
  queries; use those, or the admin API, not the raw column, for anything
  that matters).
- `retryable_failure` on the central side being rare/hard to reproduce
  under live load is expected in this phase's architecture (Section 8 of
  `docs/architecture/EDGE_ARCHITECTURE.md`) -- it is not evidence the
  retry path is broken; it is covered by fault-injection unit tests
  instead.
