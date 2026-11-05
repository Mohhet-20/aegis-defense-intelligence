# Analyst Review Workflow

One shared discipline across two different
tables -- `EvidenceRelationship` review and `Conflict` resolution --
documented together here because they share the same underlying
pattern: a machine-produced or analyst-produced candidate state that
only ever changes through an explicit, audited, human decision.

## The shared pattern

1. Something is created in a neutral starting state
   (`EvidenceRelationship.review_status = "candidate"`,
   `Conflict.review_status = "unresolved"`).
2. An analyst makes an explicit decision through a dedicated endpoint.
   Nothing in either service module EVER changes these fields as a
   side effect of anything else -- not ingestion, not a fusion run, not
   another record's review.
3. The decision and the state change are written in the SAME database
   transaction as the audit record describing it
   (`audit_service.record()` called from inside the service function,
   before `db.commit()`) -- an audit entry can never exist without the
   state change it describes actually having happened, and vice versa.
4. History is queryable per-record via the SAME append-only
   `AuditRecord` table the rest of the platform already uses --
   `audit_service.list_for_target()` (new this layer) rather than a
   second, parallel history table.
5. A later decision never silently erases an earlier one -- it's a new
   `AuditRecord` row, and for relationships, an explicit `reverse`
   action exists specifically to undo a prior review WITHOUT deleting
   history.

## `EvidenceRelationship` review

```
          create                 review(confirmed|rejected|uncertain)
(nothing) ------> candidate ------------------------------------------> {confirmed|rejected|uncertain}
                     ^                                                          |
                     |                    reverse                               |
                     +----------------------------------------------------------+
```

- `review_relationship()` (-> `POST /relationships/{id}/review`)
  rejects `"candidate"` as a target status outright -- a review is
  always a human DECISION moving a candidate forward, never a way to
  reset it (`test_review_cannot_be_set_back_to_candidate_directly`,
  and the schema's own `RelationshipReviewRequest` validator rejects
  it before the service is even called).
- `reverse_relationship()` (-> `POST /relationships/{id}/reverse`) is
  the only way back to `candidate`. It refuses to act on a relationship
  that has never been reviewed (`review_status == "candidate" and not
  is_reversed` -> `ValueError`, `test_review_confirm_reject_and_reverse_workflow`'s
  first assertion) -- there's nothing to reverse if nothing was ever
  decided. A successful reverse sets `is_reversed = True` and
  `last_reversed_at`, which persist even after the relationship is
  re-reviewed -- the fact that it was once reversed is never erased.
- Submitting the exact same review decision twice is a safe no-op
  (re-stamps `reviewed_at`/`reviewed_by_user_id`, writes a new audit
  row showing the repeat, never errors) -- consistent with Section 11's
  "make duplicate review submissions safe."

## `Conflict` resolution

```
                    resolve(explained|accepted|corrected|superseded)
unresolved ------------------------------------------------------------> {explained|accepted|corrected|superseded}
```

- `resolve_conflict()` (-> `POST /conflicts/{id}/resolve`) validates
  `review_status` against the full `CONFLICT_REVIEW_STATUSES` tuple
  (any other string is a 400 -- `test_invalid_resolution_status_is_rejected`).
- There is no separate "reverse" action for a conflict
  -- `resolve_conflict()` can itself be called again to move a conflict
  into a different resolved state (including, if ever genuinely
  needed, calling it with `review_status="unresolved"` again, since
  that value IS a member of `CONFLICT_REVIEW_STATUSES` -- but nothing
  in the UI exposes this as a normal action, since re-opening a
  resolved conflict is an edge case, not the common path).
- Resolving a conflict NEVER rewrites either underlying `Event` -- see
  `docs/analytics/CONFLICT_DETECTION.md`'s explicit statement about
  what `"corrected"` does and does not mean.

## Who can do what

Both workflows use the same two-permission split: `*_READ` (every
authenticated role, including viewer) for listing/viewing/history, and
`*_MANAGE` (administrator, analyst, investigator -- NOT viewer) for
review/resolve/reverse. See `app/core/security.py`'s `ROLE_PERMISSIONS`
table. Tested at the API level:
`test_viewer_cannot_create_a_relationship_but_can_read_one` (includes a
`403` on `POST /relationships/{id}/review` as viewer).

## History, in the same shape for both

`GET /relationships/{id}/history` and `GET /conflicts/{id}/history`
both return `list[ReviewHistoryEntry]` (`app/schemas/relationship.py`
-- reused by `conflicts.py` rather than duplicated), each entry
carrying `action`, `actor_user_id`, `outcome`, `context_metadata`
(always including `prior_status`/`new_status` for a state-changing
action), and `created_at`. A relationship's history shows
`evidence_relationship.review` and `evidence_relationship.reverse`
actions in order; a conflict's history shows `conflict.resolve` actions
in order.

## What this does NOT do

No bulk/batch review endpoint -- every decision is one record, one
explicit API call, one audit entry. No automatic escalation or
reminder system for an unreviewed candidate sitting too long. No
role-based auto-approval -- even an administrator's review goes through
the exact same `review_relationship()`/`resolve_conflict()` code path
and audit trail as anyone else's.

## Tests

`backend/tests/test_evidence_and_relationships.py::
test_review_confirm_reject_and_reverse_workflow`,
`test_review_cannot_be_set_back_to_candidate_directly`,
`test_viewer_cannot_create_a_relationship_but_can_read_one`.
`backend/tests/test_identifier_and_conflicts.py::
test_full_conflict_detection_and_resolution_workflow`,
`test_invalid_resolution_status_is_rejected`.
