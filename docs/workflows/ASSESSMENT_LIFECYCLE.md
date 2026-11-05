# Assessment Lifecycle

Implemented in `app/services/assessment_service.py`,
models `app/models/assessment.py` (`Assessment`,
`AssessmentEvidenceLink`, `AssessmentRevision`).

## What an Assessment is, and is not

An `Assessment` is a bounded, versioned, human-written judgment that
answers a stated `question`, cites the evidence it relied on, and
records its own uncertainty in the author's own words
(`assumptions`, `information_gaps`, `confidence_rationale`). It is
never computed, never a heuristic score, and never allowed to declare
something hostile on its own -- `assessment_service.py` has no code
path that writes `summary`/`confidence_level`/anything else from
analysis; every field is exactly what was submitted through the API.

## Status lifecycle

```
draft --------> in_review --------> published --------> archived
  ^                 |
  +-----------------+
       (back to draft is allowed FROM in_review only)
```

`ALLOWED_STATUS_TRANSITIONS` (`assessment_service.py`):

```python
{
    "draft": {"in_review"},
    "in_review": {"draft", "published"},
    "published": {"archived"},
    "archived": set(),
}
```

- `draft -> published` directly is refused (`ValueError`, ->
  400) -- every assessment must pass through `in_review` at least
  once before publication.
- `in_review -> draft` IS allowed -- an assessment can be pulled back
  for more work before publishing.
- `published -> draft` is refused -- once published, a correction is a
  new version (via `update_assessment()`, which still works on a
  published assessment) or a whole new assessment via `supersede()`,
  never a reopened draft.
- `archived` is terminal -- nothing moves out of it.

Tested exhaustively, including both allowed transitions and three
different refused ones, in
`test_status_transitions_follow_the_allowed_graph`.

## Versioning: snapshot-before-change, never a diff

Every call to `update_assessment()` that changes ANY tracked field
(`_TRACKED_FIELDS`: title, question, scope_description, scope_start,
scope_end, summary, assumptions, information_gaps, confidence_level,
confidence_rationale, status) does, in order, within one transaction:

1. Build a plain dict snapshot of the assessment's CURRENT (pre-update)
   state (`_snapshot()`) -- every tracked field, datetimes converted to
   ISO strings for JSON storage.
2. Write that snapshot as a new `AssessmentRevision` row, tagged with
   the version number it was taken AT (i.e. the version BEFORE this
   update), the actor, and an optional `change_note`.
3. Apply every submitted field to the live `Assessment` row.
4. Increment `Assessment.version`.
5. Write an audit record (`assessment.update`) in the same
   transaction.

This means `AssessmentRevision.version == N` always holds the state the
assessment was in WHILE it was version N, right before the update that
turned it into version N+1 -- `list_revisions()` returns them in
ascending version order, so a caller can reconstruct the assessment's
full history by replaying revisions forward. This is "version history"
in the literal, testable sense Section 17 asks for, not a vague claim:
`test_every_update_bumps_version_and_writes_a_revision_snapshot` creates
an assessment, updates it twice, and asserts both the version counter
and the exact snapshot content at each step.

Unknown field names passed to `update_assessment()` are rejected
outright (`ValueError`) rather than silently ignored --
`test_unknown_field_is_rejected`.

## Evidence traceability -- supporting and contradicting

`link_evidence()` (-> `POST /assessments/{id}/evidence`) attaches
either an `Event` or an `Evidence` item to an assessment with a role of
`supporting` or `contradicting` (`ASSESSMENT_EVIDENCE_ROLES`). It:

- requires exactly one of `event_id`/`evidence_id` (`bool(event_id) ==
  bool(evidence_id)` -> error if both or neither are set);
- validates the referenced row actually exists in this organization
  BEFORE creating the link (`test_linking_evidence_to_a_nonexistent_event_is_rejected`);
- is idempotent -- linking the same (event_id/evidence_id, role) twice
  returns the existing link with `created=False`
  (`test_duplicate_evidence_link_is_idempotent`), same pattern as
  `relationship_service.create_relationship()`.

An assessment's evidence links split cleanly into two groups via
`list_evidence_links()`, which the frontend's Assessment workspace
renders as two separate "Supporting evidence" / "Contradicting
evidence" lists -- never merged into one undifferentiated citation
list (`test_evidence_traceability_supporting_and_contradicting`).

## Supersession

`supersede_assessment(old, new, actor_user_id)` sets
`old.superseded_by_assessment_id = new.id` and writes an
`assessment.supersede` audit record. This is a deliberate ANALYST
action, never automatic -- nothing in `update_assessment()` or
`create_assessment()` ever sets this field as a side effect. (No
dedicated API route wraps this function yet -- see "What this does NOT
do" below; the service function exists and is directly testable, but
exposing it as a one-click frontend/API action is deferred.)

## What this does NOT do

No automatic conclusion generation -- `summary`/`confidence_level`/
`confidence_rationale` are always exactly what was submitted through
the API, never computed from the linked evidence. No numeric
confidence score (see `docs/analytics/
CONFIDENCE_AND_SOURCE_RELIABILITY.md`). No API route for
`supersede_assessment()` yet -- the service function is implemented and
unit-testable, but Section 12's "create a new version that supersedes
an old one" workflow is only reachable today by an analyst creating a
new `Assessment` and someone with direct service/future-route access
calling `supersede_assessment()`; wiring a `POST
/assessments/{id}/supersede` endpoint is reasonable follow-up,
documented here rather than silently assumed to exist. No deletion of
an assessment or a revision -- both are permanent, append-only records.

## Tests

`backend/tests/test_assessments.py` (12 tests): creation defaults
(`version=1`, `status="draft"`), invalid confidence level rejection,
the full status-transition graph (allowed and refused moves),
version-bump + revision-snapshot verification across two consecutive
updates, unknown-field rejection, supporting/contradicting evidence
traceability, nonexistent-reference rejection, duplicate-link
idempotency, assumptions/information_gaps stored verbatim, and two
API-level tests (`viewer` blocked from `PATCH`, revision history
visible through `GET /assessments/{id}/revisions`).
