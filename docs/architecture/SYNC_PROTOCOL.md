# Edge Synchronization Protocol

**Status: IMPLEMENTED.** Version string: `EDGE_SYNC_PROTOCOL_VERSION =
"edge_sync_v1"` (`app/schemas/edge_sync.py`). These Pydantic models **are**
the documented protocol -- `app/edge/simulator.py` imports the same classes
to construct a real request rather than maintaining a second, independently-
drifting copy of the shapes.

## 1. Transport and authentication

Every protocol endpoint is device-authenticated, never JWT-authenticated:
`POST /api/v1/edge/sync/batch` and `POST /api/v1/edge/sync/health`, both
behind `require_device_auth` (`X-Device-Id`/`X-Device-Api-Key` headers --
see `docs/security/EDGE_DEVICE_SECURITY.md`).

## 2. The batch envelope

`SyncBatchRequest`:

| Field | Type | Notes |
|---|---|---|
| `protocol_version` | `str` | Must be in `SUPPORTED_EDGE_SYNC_PROTOCOL_VERSIONS` (`("edge_sync_v1",)`) or the **whole batch** is rejected with HTTP 400 -- individual records inside an unsupported-version batch are never processed. |
| `device_id` | `str` | The device's own `device_identifier`. The route rejects the batch with 400 if this doesn't match the authenticated device's real identity (`payload.device_id != device.device_identifier` in `app/api/routes/edge_sync.py`) -- a deliberate anti-spoofing check: a device cannot submit a batch claiming to be a different device_id than the one its credentials authenticated as. |
| `batch_id` | `str \| None` | Caller-supplied grouping id, stored on every `SyncRecord` the batch produces. |
| `sent_at` | `datetime` | When the device dispatched this HTTP request. |
| `records` | `list[SyncRecordEnvelope]` | Capped at `MAX_BATCH_SIZE` (100) by the Pydantic field itself (`Field(max_length=MAX_BATCH_SIZE)`), and separately re-checked against the configurable `EDGE_SYNC_MAX_BATCH_SIZE` setting in `edge_sync_service.ingest_batch()`, which raises `BatchTooLargeError` (-> HTTP 400) if exceeded. |

## 3. The record envelope

`SyncRecordEnvelope` -- one logical record a device wants synced:

| Field | Type | Notes |
|---|---|---|
| `message_id` | `str` (1-100 chars) | Identifies **this attempt**. A retry of the same logical record gets a fresh `message_id` (see `LocalEdgeStore.mark_syncing()`, which regenerates it). |
| `idempotency_key` | `str` (1-150 chars) | Identifies the **logical operation** and must stay identical across every retry of the same record. This is the field the uniqueness guarantee is keyed on (Section 5 below). |
| `record_type` | `str` | One of `SYNC_RECORD_TYPES`: `observation_capture`, `event_capture`, `annotation`, `inference_output`. |
| `client_record_id` | `str` (1-150 chars) | The device's own stable identifier for the logical record (e.g. a locally-generated UUID for one captured observation). |
| `schema_version` | `str` (1-20 chars) | Versions the `payload` shape, independent of the protocol envelope version. |
| `payload` | `dict` | The actual record content -- opaque to the protocol layer itself. |
| `payload_hash` | `str \| None` (≤64 chars) | If omitted, the server computes it itself (`_compute_payload_hash()`, SHA-256 over `json.dumps(payload, sort_keys=True, default=str)`). Used for the immutable-type integrity check (Section 6). |
| `source_created_at` | `datetime` | When the device **captured** this record. |
| `queued_at` | `datetime` | When the device's **local outbox enqueued** it. |
| `base_revision` | `int \| None` | **Only meaningful for a mutable `record_type`** (`annotation`) -- the revision this submission claims to be based on. Omitted entirely for an immutable/append-only type; required (and quarantined as `validation_error` if missing) for `annotation`. |

## 4. The four distinct timestamps, and why

Every `SyncRecord` carries four separate timestamps, deliberately never
collapsed into one "timestamp" field:

| Timestamp | Meaning | Who sets it |
|---|---|---|
| `source_created_at` | When the device **captured** the data. | Device, in the envelope. |
| `queued_at` | When the device's **local outbox enqueued** the attempt. | Device, in the envelope. |
| `created_at` (`TimestampMixin`) | When the **central** system first received this attempt -- this is the real "received_at." | Central, on row insert. |
| `processed_at` | When the record left `syncing` for a terminal, conflict, or quarantine state. | Central, in `edge_sync_service`. |
| `acknowledged_at` | When the central system finished producing the acknowledgment the device will see. | Central, alongside `processed_at` in the accept paths. |

**Central ordering is always by central receipt order** (`created_at` /
central DB state) -- a device's own clock never determines which revision
is "current" for a mutable record. `_get_current_accepted()`
(`edge_sync_service.py`) orders strictly by `SyncRecord.created_at.desc()`,
never by `source_created_at`. This is deliberate: a device with a wrong or
skewed clock must never be able to make its submission look "newer" than it
actually arrived, which is exactly the vulnerability a naive
device-timestamp-based ordering scheme would have.

## 5. Idempotency: `idempotency_key` vs. `message_id`

`idempotency_key` identifies the logical operation; `message_id` identifies
one attempt at sending it. The idempotency guarantee itself is a real
database unique constraint --
`UniqueConstraint("organization_id", "device_id", "idempotency_key", name="uq_sync_records_device_idempotency")`
on `sync_records` -- not merely a convention the service layer happens to
follow. `edge_sync_service._get_or_create_record()` looks up an existing row
by `(organization_id, device_id, idempotency_key)` before ever inserting;
re-submission with the same key returns the **existing** row, and
`process_record()` treats a non-new record already in a terminal (or
awaiting-human-resolution) state as an idempotent no-op -- it reflects
current state, it never reprocesses. A fresh `message_id` on a retry (as
`LocalEdgeStore.mark_syncing()` generates) lets the server's own logs/audit
trail distinguish separate attempts at the same logical operation without
affecting the idempotency guarantee at all.

## 6. Acceptance: the two-tier policy (summary)

Full detail in `docs/operations/CONFLICT_RESOLUTION.md`. In one sentence:
immutable types (`observation_capture`, `event_capture`, `inference_output`)
treat a same-`client_record_id`-same-`payload_hash` resubmission as a benign
no-op and a same-`client_record_id`-different-`payload_hash` resubmission as
`quarantined` (`integrity_failure`, never merged, never silently
overwritten); the one mutable type (`annotation`) uses
`base_revision`/`revision` optimistic concurrency, and a mismatch creates a
real `SyncConflict` row for human resolution.

## 7. Response envelopes

`SyncRecordAckResponse` -- one per submitted record: `message_id`,
`idempotency_key`, `client_record_id`, `sync_record_id`, `sync_status`,
`error_category`, `error_message`, `conflict_id` (set only when this
attempt produced a new `SyncConflict`), `retry_after_seconds` (a `float`,
not an `int` -- `compute_backoff_seconds()` applies jitter, so this is
deliberately sub-second-precise rather than rounded).

`SyncBatchResponse` -- one per batch request: `protocol_version`,
`batch_id`, `accepted_count`, `conflict_count`, `quarantined_count`,
`rejected_count` (everything not accepted/conflicted/quarantined --
in this layer's synchronous architecture, that is effectively zero in
normal operation, since the only other terminal-this-request outcomes are
quarantine or conflict; see
`docs/architecture/EDGE_ARCHITECTURE.md` Section 8), `results` (the list of
`SyncRecordAckResponse`).

## 8. Health reporting

`POST /api/v1/edge/sync/health` accepts `HealthReportRequest`
(`protocol_version`, `reported_at`, `connectivity_state`,
`resource_metrics`, `queue_depth`, `pending_sync_count`, `model_status`,
`software_version`, `runtime_capabilities`) and persists one append-only
`DeviceHealthReport` row via `edge_sync_service.process_health_report()`,
which also updates `Device.last_health_report_at`/`connectivity_state`/
`software_version`/`local_storage_status`. Returns
`HealthReportAckResponse` (`report_id`, `received_at`). Same
protocol-version check and rejection behavior as the batch endpoint.

## 9. Limits, all server-enforced

| Limit | Default | Enforced where |
|---|---|---|
| Batch size | `MAX_BATCH_SIZE` = 100 (schema) and `EDGE_SYNC_MAX_BATCH_SIZE` = 100 (config) | Pydantic field cap + `ingest_batch()`'s explicit re-check (`BatchTooLargeError`). |
| Payload size | `EDGE_SYNC_MAX_PAYLOAD_BYTES` = 262144 (256KB) | `process_record()` quarantines (`validation_error`) a record whose serialized payload exceeds this, checked once per new record before acceptance is attempted. |
| Retry count | `EDGE_SYNC_MAX_RETRY_COUNT` = 10 | `_run_acceptance()`/`recover_stale_syncing_records()` move a record to `permanent_failure` once its `retry_count` reaches this. |
| Backoff | `EDGE_SYNC_RETRY_BASE_DELAY_SECONDS` = 5.0, `EDGE_SYNC_RETRY_MAX_DELAY_SECONDS` = 3600.0, `EDGE_SYNC_RETRY_JITTER_FRACTION` = 0.2 | `compute_backoff_seconds()` -- exponential, bounded, symmetric jitter. |
| Stale `syncing` | `EDGE_SYNC_SYNCING_STALE_AFTER_SECONDS` = 300.0 | `recover_stale_syncing_records()`. |

## 10. What this protocol does NOT do

- It never trusts a device's self-reported clock for authoritative
  ordering (Section 4).
- It never silently drops or auto-merges a conflicting mutable-record
  submission (see `docs/operations/CONFLICT_RESOLUTION.md`).
- It never processes part of a batch under an unsupported protocol version
  -- rejection is all-or-nothing.
- It carries no location/geospatial fields of its own; a payload that needs
  one uses the existing `GeoLocationMixin`/`app/geo/` conventions inside its
  own `payload` dict, not a protocol-level field.
