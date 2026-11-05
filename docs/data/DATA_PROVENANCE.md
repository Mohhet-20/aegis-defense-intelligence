# Data Provenance

Every record that reaches the ingestion engine --
accepted, rejected, quarantined, or flagged a duplicate -- gets a
`RawRecord` row (`app/models/raw_record.py`). This is deliberate: an
analyst can inspect exactly what a source sent, even for a record this
platform decided not to use as evidence.

## What's stored on every `RawRecord`

| Field | Meaning |
|---|---|
| `source_id`, `ingestion_job_id` | which source and which batch produced it |
| `event_id` | set ONLY if this record was accepted as a new, non-duplicate `Event` -- `NULL` for a rejected, quarantined, or duplicate record |
| `external_record_id` | the source's own id, or the fallback content fingerprint |
| `connector_type`, `connector_version` | which connector produced it, and which version -- lets a later reprocessing pass know exactly which code path is responsible |
| `normalization_version`, `schema_version` | which normalization rules and which canonical schema version were applied |
| `content_fingerprint` | sha256-derived, documented, versioned (see `DEDUPLICATION_POLICY.md`) |
| `payload` | the record **exactly as received**, before normalization |
| `source_observed_at_raw` | the UNPARSED original timestamp string -- normalization owns parsing, this preserves what was actually said |
| `received_at` | when this platform received the batch |
| `validation_status`, `validation_errors`, `validation_warnings` | the full structured outcome from the validation engine (see `app/services/validation_service.py`) |
| `is_duplicate`, `duplicate_of_raw_record_id`, `duplicate_reason` | if flagged duplicate, which earlier raw record it duplicates and why |

The original payload is never overwritten during normalization -- a
`RawRecord` row is immutable once written (no update route exists for it).
If retention policy ever required deleting a raw payload, the metadata
columns above (everything except `payload`) could be preserved to keep an
audit trail while discarding the sensitive body; **no such deletion path
is implemented** -- see `DEDUPLICATION_POLICY.md`'s
retention note.

## The raw <-> normalized link

- `Event.provenance.raw_record_id` points forward to the `RawRecord` that
  produced it.
- `RawRecord.event_id` points back. Both are set in the same database
  transaction (`app/services/ingestion_service.py::_process_batch`), so
  they can never disagree.
- `GET /api/v1/events/{id}/raw-record` resolves an event to its raw record
  for an authorized caller.

## Access control

Raw-record access is gated by its own permission, `RAW_RECORD_READ`
(`app/core/security.py`) -- **separate from** `EVENT_READ` and
`INGESTION_READ`. Rationale: a raw payload may carry source-side detail a
normalized `Event` intentionally drops (extra fields, a source's internal
identifiers, free-text that didn't fit a dedicated column). Granted to
administrator, analyst, and investigator roles; **not** granted to viewer.

Endpoints gated this way:
- `GET /api/v1/events/{event_id}/raw-record`
- `GET /api/v1/ingestion/jobs/{job_id}/raw-records`

## What this does NOT do

There is no cryptographic chain-of-custody / tamper-evidence (hash
chaining, signing) over raw records -- `content_fingerprint`
is a content-identity hash for deduplication, not a tamper-evidence
mechanism. If that requirement arises in later work, it is a new,
explicit feature, not something to assume already exists here.
