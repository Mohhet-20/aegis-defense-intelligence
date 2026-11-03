# Investigation Workspace, Evidence Provenance and Review (Phase 11)

Extends the existing `Investigation` and `Evidence` models. No parallel case or evidence model was created.
The platform remains human-reviewed decision support; nothing here triggers an action.

## Data model

| Table | Purpose | History |
|---|---|---|
| `investigations` (extended) | + `tags`, `closure_reason`, `closed_at`, `archived_at`, `is_restricted`; new statuses `draft`, `archived` | updated in place; every status change is also in `investigation_status_history` |
| `investigation_status_history` | one row per lifecycle transition (from, to, reason, actor) | append-only |
| `investigation_members` | `reviewer` / `member` per investigation (owner is `assigned_user_id`) | add/change/remove are audited |
| `investigation_links` | reference from an investigation to an existing record (event, observation, assessment, data_source, sensor, media_asset, evidence, detection_result, track); unique per pair | removal audited |
| `evidence_items` (extended) | + `access_classification`, `review_status`, `captured_at`, `processing_version`, `media_asset_id`, `source_id`, hash algorithm/time, `supersedes_evidence_id`, `superseded_by_evidence_id`; new types `media_asset`, `detection`, `track`, `data_source`, `assessment_version` | superseding adds a row; the old row is kept |
| `evidence_integrity_checks` | result of each integrity verification | append-only |
| `investigation_notes` | note/annotation, optional evidence, one-level replies, `version` | see revisions |
| `investigation_note_revisions` | full content of every note version | append-only |

Migration: `6e2842cef39a` (after `75b9cd8a733e`), tested up/down/up. Existing rows stay valid (new columns are
nullable or defaulted). The legacy `linked_event_ids` / `evidence_refs` JSON lists are still honoured as read-only links.

Evidence is a reference layer: platform records are referenced with `aegis://<type>/<id>` URIs and the existing FK
columns; bytes are never copied. If evidence for the same record already exists in the organization it is reused and
linked instead of duplicated.

## Lifecycle

`draft -> open -> active <-> open`, `open|active -> pending_review` (the repository's "under review"), any of
`open|active|pending_review -> closed`, `closed -> open` (reopen) or `closed -> archived` (terminal, read-only).
`open -> closed` was already legal and stays so. Closing requires a closure reason (`reason` or `resolution_notes`).
Invalid transitions return 409. Restricted investigations are visible only to the owner, members and administrators;
everyone else gets 404 (same answer as "does not exist").

## Timeline timestamp semantics

The timeline is computed on read from persisted records (nothing stored or back-filled). Each entry has a single
`time_kind`: `event_time`, `observation_time`, `capture_time`, `registration_time`, `ingestion_time`,
`processing_time`, `review_time`, `association_time`, `integrity_check_time`, `note_time`, `status_change`,
`record_created`. Different clocks are separate entries and are never merged.

* All times are UTC. Stored values without an offset are read as UTC and marked `assumed_utc`.
* The original source offset is shown only if the record's provenance carries one (`original_timezone`); otherwise null.
* A time that was never recorded (media capture time, an observation's `ingested_at` when unset, evidence
  `captured_at` when unknown) yields an entry with `timestamp: null`, `time_known: false` and an explanatory note.
  Such entries sort last and are excluded when a date range is set.
* Ordering: known times first, then `(timestamp, kind rank, record type, record id, entry id)` - stable for ties.
* The response carries a notice that proximity in time does not imply causation. Capped at 5000 entries (`truncated`).

## Integrity and provenance guarantees (and limits)

* SHA-256 is recorded when media evidence is registered (the stored media hash) and when text evidence is registered.
  Externally referenced documents keep only a hash the user supplied, marked unverified.
* `POST /evidence/{id}/verify-integrity` re-reads the stored file through the controlled storage layer (content-addressed
  key, path-traversal-checked) or re-hashes stored text and compares it with the recorded value. Results: `match`,
  `mismatch`, `original_unavailable`, `no_recorded_hash`, `not_file_backed`. Each check is appended; the recorded hash is
  never rewritten and a missing hash is never invented as a baseline.
* **A match shows only that today's bytes hash to the recorded value.** It does not show the source was authentic, that
  the content was unaltered before first hashing, or that it is true. Text evidence is editable by the older evidence
  route; an edit makes later checks report `mismatch` (use supersede for a clean new version).
* Provenance is derived from existing foreign keys (detection -> inference job -> model, media asset, event ->
  ingestion job, source). Unresolvable hops are reported as unavailable and unknown values stay null.
* The audit trail (`audit_records`) is an application log of actions made through AEGIS. It is **not** a legally
  certified chain of custody, is not tamper-proof against someone with database access, and is not cryptographically chained.

## Notes and annotations

Kinds: `observed_fact`, `analyst_interpretation`, `hypothesis`, `review_question` (can be assigned and resolved).
Each edit requires `expected_version`; a stale value returns 409 and nothing is overwritten. Every version is stored in
`investigation_note_revisions`. Only the author (or an administrator) can change content; resolution and assignment can be
changed by any user who can manage investigations. Notes never modify evidence rows, files or model outputs.

## Search and relationships

Search covers only records linked to the investigation (plus its notes): text, record type, source, time range, evidence
review status, data quality (`clean`/`flagged`/`unknown` - unknown for record types without a quality indicator), tag.
Relationships reuse `evidence_relationships` and show origin (rule / model / analyst) and review status. Nothing here
promotes a candidate or uncertain relationship.

## Export format

`POST /investigations/{id}/export?format=json|zip&include_media=false|true` (permission `investigation:export`, audited).
Contents: investigation metadata, members, status history, linked records, evidence index with provenance and latest
integrity check, assessments with review history, notes with revisions, ordered timeline, `omitted_artifacts` with reasons,
`content_sha256` (hash of the report body excluding generation metadata, so unchanged data reproduces it), `generation`
(`generated_at` - build time only), and an authenticity notice.
ZIP layout: `README.txt`, `report.json`, `manifest.json`, `media/<sha256>.<ext>`; fixed zip timestamps, sorted names.
`manifest.json` lists SHA-256 and size for every file except itself. Media bytes are included only on request, only when
they still hash to the recorded value; limits: 10 MB per file, 25 MB and 25 files per bundle (excess is listed as omitted).
Restricted evidence is omitted for any role that cannot view it (a defensive check: every role holding the export permission can currently view restricted evidence, so it does not trigger today). **The export is not independently authenticated or signed.**

## Known limitations / deferred

* The platform does not record when media was captured; only registration time is known.
* No retention/deletion workflow for investigations, evidence or notes was added (nothing is deleted; links and members
  can be removed and are audited). A retention policy remains future work.
* Restricted-investigation access is per-investigation, not per-evidence-item beyond `access_classification`.
* Search and timeline are computed in memory per request (bounded at 5000 entries); very large cases may need pre-indexing.
* Hash verification covers media and stored text; externally hosted documents cannot be fetched or verified.
* No reviewer sign-off workflow beyond evidence `review_status` and resolvable review questions.
* Frontend was type-checked, linted and built but not exercised in a browser; no frontend unit tests exist in the repo.
