# Local Storage and Retention

**Status: IMPLEMENTED, with an honestly-documented retention gap.** This
document covers the edge-side local outbox schema/lifecycle and the
central tables' retention behavior. **No automatic retention or purge job
exists anywhere** -- every table described below keeps rows
indefinitely until an explicit cancel or (not-yet-built) purge action.
This is stated as a known gap, not papered over with an invented policy
that isn't actually coded.

## 1. The edge-side local outbox (`app/edge/local_store.py`)

A separate SQLite database file per device, opened with raw `sqlite3`
(never the central app's SQLAlchemy session). Schema (`outbox` table):

| Column | Notes |
|---|---|
| `id` | Primary key (UUID). |
| `idempotency_key` | `UNIQUE NOT NULL` -- the local-side idempotency guarantee, mirroring the central unique constraint. |
| `message_id` | Regenerated on every `mark_syncing()` call -- identifies the current attempt. |
| `record_type`, `client_record_id`, `schema_version`, `payload`, `payload_hash`, `base_revision` | The logical record itself. |
| `source_created_at`, `queued_at` | Set once, at `enqueue()` time. |
| `local_status` | Mirrors `SYNC_RECORD_STATUSES`, enforced by the same `SYNC_RECORD_TRANSITIONS` table the central side uses. |
| `retry_count`, `next_retry_at`, `last_error_category`, `last_error_message` | Local retry bookkeeping. |
| `sync_record_id` | Set from the server's ack once known. |
| `created_at`, `updated_at` | Row bookkeeping; `updated_at` is what `recover_crashed()`'s staleness check reads. |

### Lifecycle

`queued` (on `enqueue()`) -> `syncing` (on `mark_syncing()`, immediately
before a send attempt) -> one of `synced` / `retryable_failure` /
`permanent_failure` / `conflict` / `quarantined` (mirroring the server's
ack via `apply_ack()`) or `cancelled` (via `cancel()`). A row is **never
deleted on mere HTTP-request-initiation** -- only `mark_synced`-equivalent
acks (`apply_ack(sync_status="synced")`) and `cancel()` retire a row from
the *pending* set, and even then the row itself is **kept, not deleted**,
as local history.

### What's retained, and for how long

**Indefinitely.** There is no automatic purge of `synced`, `cancelled`,
`permanent_failure`, or `quarantined` rows in the local outbox -- `enqueue()`
never checks a row count or age before inserting, and no method in
`LocalEdgeStore` deletes a row. A real, long-lived device would need an
operator- or application-level purge step added later; none exists today.
This is a known, explicitly stated gap, not a documented retention window
that isn't actually enforced.

## 2. Central tables: `SyncRecord`, `SyncConflict`, `DeviceHealthReport`

All three are plain, append-oriented SQLAlchemy models with **no retention
or purge job** anywhere:

- **`SyncRecord`** (`sync_records`) -- one row per logical sync attempt,
  ever. Rows reaching a terminal state (`synced`, `permanent_failure`,
  `cancelled`) are never deleted or archived; they remain the permanent,
  queryable record of what happened, by design (Section 7 of
  `docs/architecture/EDGE_ARCHITECTURE.md` -- this table **is** the
  durable store, not a staging area). There is no `DELETE` anywhere in
  `edge_sync_service.py`.
- **`SyncConflict`** (`sync_conflicts`) -- one row per detected revision
  conflict, resolved or not. `resolve_conflict()` updates a row's
  resolution fields; it never deletes one. A resolved conflict remains
  permanently queryable as an audit record of the decision made.
- **`DeviceHealthReport`** -- explicitly append-only self-reported health
  snapshots, one per `POST /edge/sync/health` call, capped only by
  `EDGE_DEVICE_HEALTH_REPORT_MAX_RESULTS` (200) on how many are returned
  per **query** (a pagination/display cap, not a storage cap) -- every
  report a device has ever sent remains in the database.

### Honest statement of the gap

Retention for all three tables is **indefinite, with no purge job
implemented** -- the same honest gap as the local outbox above, not an
invented retention policy. A real production deployment running this
system for an extended period, with many devices syncing frequently, would
need a retention/archival policy added (likely as part of the
"retention policies" scope, or an earlier operational necessity) before
these tables grow unboundedly. Nothing estimates row-growth
rate or proposes a specific retention window, because no such policy has
been designed or coded yet -- stating a number here would be inventing a
policy that doesn't exist.

## 3. Why this is the honest answer, not an oversight

Every other durability claim is backed by an actual test
(local-store close/reopen durability, idempotency-key uniqueness,
transition-table enforcement). Retention/purge has no corresponding test
because no corresponding code exists -- adding a specific number here
(e.g. "retained for 90 days") without the enforcement to back it would
violate this project's standing "don't claim what wasn't built" discipline. This gap is
listed explicitly in `docs/architecture/EDGE_ARCHITECTURE.md` Section 16 as well.

## 4. What a future retention implementation would need to decide

Not built, but the natural follow-up questions for whoever builds it:

- A terminal `SyncRecord`/local outbox row's audit value likely needs a
  longer retention window than a transient `retryable_failure` one still
  mid-backoff -- today both are kept identically, forever.
- `DeviceHealthReport` volume scales with report frequency × device count
  × uptime -- the most likely candidate for an actual purge/aggregation
  job first, since it has no inherent long-term audit value once
  superseded by a later report.
- Any purge policy must not remove a `SyncRecord` still referenced by an
  **unresolved** `SyncConflict` (`sync_record_id` FK) or by
  `supersedes_sync_record_id` chains that a future audit might need to
  walk.
