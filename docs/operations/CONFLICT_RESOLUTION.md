# Conflict Resolution

**Status: IMPLEMENTED, tested.** This document covers the full two-tier
sync-conflict policy, the three resolution strategies and their exact
effects, and the Section 8.4 review API. It is **deliberately separate**
from the `Conflict`/`conflict_service.py`: that model detects an
event-correlation contradiction between two already-correlated `Event`
rows (an event-fusion concern); `SyncConflict` here detects a sync-time
revision mismatch between an edge device's submitted payload and the
central system's current state (a synchronization-protocol concern). The
two models, services, and review queues never share a table or a function
call -- see `app/models/sync_conflict.py`'s module docstring for the
authoritative statement of this boundary.

## 1. The two-tier policy

Record types split into two tiers, enforced in
`edge_sync_service._accept_record()`:

### Tier 1 -- immutable types (`observation_capture`, `event_capture`,
`inference_output`)

Handled by `_accept_immutable()`. A resubmission of the **same**
`client_record_id` with the **same** `payload_hash` is a benign duplicate --
accepted idempotently, moved straight to `synced`. A resubmission of the
**same** `client_record_id` with a **different** `payload_hash` is
**quarantined** (`error_category="integrity_failure"`) -- never merged,
never silently overwritten. A quarantined record requires an explicit human
decision (there is no auto-resolve path for `quarantined`; its only legal
transition is to `permanent_failure`, and only via explicit operator
action).

### Tier 2 -- the one mutable type (`annotation`)

Handled by `_accept_mutable()`, using `base_revision`/`revision` optimistic
concurrency. The submission's `base_revision` is compared against the
current central revision (`_get_current_accepted()`, ordered strictly by
central receipt order -- see `docs/architecture/SYNC_PROTOCOL.md` Section
4). A match advances the record to `revision = current_revision + 1` and
`synced`, recording `supersedes_sync_record_id`. A mismatch creates a real
`SyncConflict` row with full `local_version`/`central_version` JSON
snapshots and moves the submitting `SyncRecord` to `conflict` -- **requiring
human resolution**, never an automatic merge or an automatic
"newest wins."

## 2. Why this is never last-write-wins

Every resolution path in this system is an explicit, authorized, audited
human action recorded in `resolution_strategy`/`resolved_by_user_id`/
`resolved_at` (`SyncConflict`). Nothing in `edge_sync_service.py` or
`edge_conflict_service.py` ever picks a winner by comparing timestamps --
central ordering already never trusts a device's clock (Section 4 of
`SYNC_PROTOCOL.md`), and even the comparison that *is* trustworthy (central
receipt order, used only to detect whether a conflict exists at all) is
never used to silently resolve one once detected.

## 3. The three resolution strategies and their exact effects

`SyncConflict.resolution_strategy` ∈ `keep_central` / `keep_local` /
`merged`. Applied by `edge_conflict_service.resolve_conflict()`:

| Strategy | Effect on the conflicting `SyncRecord` | Effect on the central "current" revision |
|---|---|---|
| `keep_central` | Moves to `permanent_failure`. | Unchanged -- the device's submitted revision is discarded; it never becomes authoritative. |
| `keep_local` | Advances to `revision = central_revision + 1`, `sync_status = "synced"`. | The device's submitted revision **becomes** the new current revision, superseding whatever was central at conflict time. |
| `merged` | Moves to `permanent_failure` -- **same as `keep_central`**. | Unchanged by this call. The reviewer's merged content, recorded only in free-text `resolution_note`, is never taken as the device's payload verbatim; if the merged outcome needs to become the new central record, a human enters it through the normal device/analyst submission path. |

**`merged` explicitly never takes the device's submitted payload verbatim
-- there is no generic field-level merge UI.** A human composes the
merged outcome externally; the system records that a merge decision was
made and why, but does not fabricate the merged record from a free-text
note. This is why `merged`'s effect on the `SyncRecord` is identical to
`keep_central`'s: in both cases the device's own submission, as submitted,
is not what becomes authoritative.

`resolve_conflict()` also raises `ConflictAlreadyResolvedError` on a
second resolution attempt and `InvalidConflictResolutionError` on an
unrecognized `resolution_strategy` -- a conflict is resolved exactly once.

## 4. The Section 8.4 API

| Route | Permission | Behavior |
|---|---|---|
| `GET /api/v1/edge/conflicts` | `EDGE_CONFLICT_READ` | Paginated list, filterable by `resolution_status`/`device_id`/`record_type`. |
| `GET /api/v1/edge/conflicts/{conflict_id}` | `EDGE_CONFLICT_READ` | Full detail incl. both `local_version`/`central_version` JSON snapshots. |
| `POST /api/v1/edge/conflicts/{conflict_id}/resolve` | `EDGE_CONFLICT_MANAGE` | Body: `resolution_strategy`, optional `resolution_note`. |

Every resolution writes an `audit_service.record()` entry
(`action="edge_conflict.resolve"`) carrying the `resolution_strategy`,
`sync_record_id`, and `resolution_note` -- a full audit trail of who
resolved what, how, and when, same discipline every prior review workflow
in this codebase (relationship review, anomaly review, assessment
supersession) already follows.

## 5. The Investigator-can-resolve-but-not-manage-devices permission split

Investigator is granted `DEVICE_READ` + `EDGE_SYNC_READ` +
`EDGE_CONFLICT_READ` + `EDGE_CONFLICT_MANAGE` -- deliberately **including**
`EDGE_CONFLICT_MANAGE`. Reviewing and resolving a conflicting field
submission is case-work: an Investigator deciding whether a device's
updated annotation or the central system's existing one should stand is the
same category of judgment call as reviewing evidence (`EVIDENCE_MANAGE`,
which Investigator also has). It is **not** fleet
administration: Investigator cannot register, activate, suspend, or revoke
a device (`DEVICE_MANAGE`), and cannot force-retry or cancel a sync record
(`EDGE_SYNC_MANAGE`) -- those are operational decisions about the fleet
itself, not about the content of a specific conflicting record. This
mirrors the "can review/resolve case-work, cannot administer the
infrastructure producing it" boundary already drew for
Investigator across inference jobs, tracking jobs, and sensor ingestion.

Full role matrix:

| Permission | Administrator | Analyst | Investigator | Viewer |
|---|---|---|---|---|
| `DEVICE_READ` | yes | yes | yes | yes |
| `DEVICE_MANAGE` | yes | yes | no | no |
| `EDGE_SYNC_READ` | yes | yes | yes | yes |
| `EDGE_SYNC_MANAGE` | yes | yes | no | no |
| `EDGE_CONFLICT_READ` | yes | yes | yes | yes |
| `EDGE_CONFLICT_MANAGE` | yes | yes | **yes** | no |

## 6. Known gaps

- No generic merge UI exists for the `merged` strategy -- by design, not
  oversight (Section 3).
- Only one mutable record type (`annotation`) is defined; a
  future record type that needs revisioned conflict handling would extend
  `MUTABLE_SYNC_RECORD_TYPES`, not duplicate this logic.
- Conflict detection is scoped to one organization's own
  `(record_type, client_record_id)` pair -- cross-organization conflicts are
  not meaningful under this platform's tenant-isolation model and are not
  handled (nor should they be).
