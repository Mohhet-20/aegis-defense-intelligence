# Deduplication Policy

How this platform decides a record is a duplicate,
and -- just as important -- what it refuses to do about an updated record.

## Matching order (deterministic, never similarity-based)

Implemented in `app/services/ingestion_service.py::_process_batch`:

1. **`source_id` + the connector-supplied `external_id`** (the field the
   source itself calls a stable record identifier), if present.
2. **A content fingerprint** (`normalization_service.content_fingerprint`)
   when no `external_id` is supplied -- `sha256` over the record's own
   fields, JSON-encoded with keys sorted (so key order never matters) and
   `default=str` for non-serializable values, truncated to 32 hex
   characters. This is a documented, versioned algorithm
   (`NORMALIZATION_VERSION`) -- changing it is a breaking change for
   existing fingerprints.

**Never on description similarity, fuzzy matching, or any heuristic.**
Two records are either the same identifier (or fingerprint) or they are
not; there is no "probably the same" tier here. (Rule-based *correlation*
of genuinely different events that might be related is a separate,
explicitly-labeled feature -- see `EVENT_CORRELATION.md` -- and never
feeds back into deduplication.)

## Where duplicates are caught

1. **In-batch**: `seen_external_ids`, a set built fresh for each
   connector batch -- catches two records in the SAME upload/fetch sharing
   an identifier before either is committed. (This set is exactly the fix
   for the intra-batch `IntegrityError` bug found and fixed,
   carried forward unchanged in behavior through this layer's rewrite.)
2. **Cross-batch, pre-insert**: a `SELECT` against `Event` for
   `(source_id, external_id)` before attempting an insert.
3. **The database constraint, as the real backstop**: `events` has
   `UniqueConstraint("source_id", "external_id", name="uq_events_source_external_id")`.
   Checks 1 and 2 catch the overwhelming majority of cases, but neither
   closes the window between "checked, nothing exists" and "committed"
   that a genuinely concurrent second request could race through. When
   the DB constraint is the one that fires, `_process_batch` catches the
   resulting `IntegrityError` **inside a SAVEPOINT**
   (`db.begin_nested()`), so the failed insert is rolled back without
   poisoning the rest of the batch's transaction, and the record is
   reported as an ordinary counted duplicate rather than a crashed job.
   Verified by
   `tests/test_provenance_and_dedup.py::test_concurrent_duplicate_attempt_is_caught_by_the_db_constraint`.

Every outcome -- accepted, duplicate, or rejected -- gets a `RawRecord`
row with an explicit `duplicate_reason` when applicable: `"external_id
repeated earlier in this same ingestion batch"`, `"external_id already
exists for this source from a previous ingestion"`, or `"external_id
uniqueness constraint violated at insert time -- a concurrent request won
the race"`.

## Updated source records: never a silent overwrite

A source resending the SAME `external_id` with DIFFERENT content (a
corrected or updated report) is still flagged a duplicate, exactly like an
exact repeat. **The existing stored event is never silently replaced.**
This is the deliberate, documented policy: preserving
original evidence takes priority over auto-applying an update. An
"ignore exact repeat / update existing / create a new versioned record"
three-way policy choice was considered (Section 11 explicitly asks for an
explicit policy here) -- the choice made is **ignore and flag**, the
safest default, with the resend visible to an analyst via the duplicate's
`RawRecord` row (which still preserves the new payload, even though no
`Event` was created or modified from it). A dedicated "apply this
correction" analyst action is a reasonable later feature; nothing in
this layer implements one, and nothing silently behaves as if it does.
Verified by
`tests/test_provenance_and_dedup.py::test_updated_record_with_same_external_id_never_silently_overwrites`.

## Tested scenarios

`tests/test_provenance_and_dedup.py` and `tests/test_ingestion.py` cover:
repeated identical upload (idempotent), overlapping batch (only the new
record accepted), an updated record with the same id (never overwrites),
and the concurrent-duplicate race condition above.

## Retention

No automated deletion of raw or normalized records exists anywhere in
this codebase. If a future retention policy requires deleting old raw
payloads, the provenance metadata columns on `RawRecord` (everything
except `payload` itself) are designed to survive that deletion -- see
`DATA_PROVENANCE.md`. That deletion mechanism is not implemented here;
documenting the extension point is not the same as building it.
