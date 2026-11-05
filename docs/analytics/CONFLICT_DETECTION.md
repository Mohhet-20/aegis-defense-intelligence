# Conflict Detection

Implemented in `app/services/conflict_service.py`,
model `app/models/conflict.py`. Read this before touching either file --
the single most important constraint here is that conflict detection is
NEVER an independent scan of the dataset.

## The core constraint: scoped to existing correlations only

`detect_conflicts()` only ever evaluates event pairs that ALREADY have
an `EventCorrelation` row (optionally narrowed to one
`correlation_batch_id`). It never runs its own all-pairs comparison.
This is deliberate and tested directly:
`test_conflict_detection_requires_an_existing_correlation` constructs
two events whose fields genuinely disagree but which were never
correlated (observed 5 hours apart, outside the correlation window) --
`detect_conflicts()` reports `pairs_considered == 0`, proving the
disagreement is never even looked at. Correlation decides
WHAT is related; conflict detection only ever asks "given
that these two are already thought to be related, do they actually
agree?"

Rejected correlation pairs are excluded from consideration
(`EventCorrelation.review_status != "rejected"` in the query) -- an
analyst who has already said "these aren't related" has their decision
respected; conflict detection doesn't re-litigate it.

## The four conflict rules

Each rule produces one entry in `Conflict.conflicting_fields`
(`[{"field", "value_a", "value_b", "rule"}]`), never an unexplained
flag:

| Rule | Fires when |
|---|---|
| `incompatible_event_type` | The pair correlated via a STRONG non-type signal (`shared_asset_reference` or `shared_source_id` present in the correlation's `reasons`), but the two `event_type` values differ (case-insensitive). Without a strong non-type signal, differing types are not flagged -- a correlation that matched ONLY on event type agreeing would be contradicting itself to then flag a type mismatch. |
| `conflicting_severity` | Both sides report a non-null `source_severity`, and the values differ. Neither side missing it is never a conflict. |
| `location` (spatial) | See `docs/analytics/SPATIAL_CORRELATION.md` for the full guard conditions -- in short, both sides have real coordinates, the pair did NOT match via `spatial_proximity`, and the distance between them exceeds the (larger, separately-configured) conflict threshold. |
| `conflicting_attribute_value` | Any `identifier_service.compare_events()` result with `outcome == "conflict"` -- a documented, allow-listed attribute key (never an arbitrary JSON diff) both sides report with disagreeing values. See `docs/data/EVIDENCE_RELATIONSHIP_MODEL.md`... no -- see `app/services/identifier_service.py`'s own docstring and `docs/analytics/CONFIDENCE_AND_SOURCE_RELIABILITY.md` for why this is namespace-aware. |

**Missing information is never negative evidence.** Every rule above
requires BOTH sides to actually have reported the field being compared
-- a field one side simply never populated contributes nothing, neither
a match nor a conflict. Tested directly:
`test_no_coordinates_on_either_side_is_never_a_spatial_conflict` (two
events with no coordinates at all, correlated via `shared_asset_reference`,
produce zero conflicts).

## Idempotency

`Conflict` has `UniqueConstraint(event_a_id, event_b_id,
conflict_rule_version)`. A rerun of `detect_conflicts()`:

- skips a pair that already has a conflict row for the current rule
  version UNLESS the computed `conflicting_fields` have actually
  changed (in which case it updates the existing row in place,
  incrementing `conflicts_updated` rather than creating a duplicate);
- never resets an already-resolved conflict's `review_status` back to
  `unresolved` -- resolution state is sticky across reruns.

Tested: `test_conflict_detection_is_idempotent` (two consecutive runs
over the same data: first creates 1, second creates 0).

## Resolution workflow -- never rewrites history

`Conflict.review_status` starts at `unresolved` and only ever changes
through `conflict_service.resolve_conflict()` ->
`POST /conflicts/{id}/resolve`, to one of `CONFLICT_REVIEW_STATUSES`:

| Status | Meaning here |
|---|---|
| `unresolved` | Default; nothing has been decided. |
| `explained` | An analyst has recorded a reason the disagreement exists, without declaring either side "correct." |
| `accepted` | An analyst has decided the disagreement is a legitimate difference (e.g. two sensors genuinely saw different things) and needs no further action. |
| `corrected` | An analyst has recorded that a correction exists ELSEWHERE (e.g. a newer, independently-reviewed event supersedes the disputed one) -- **this never means the platform edited `Event.source_severity`/`event_type`/coordinates to make the two sides agree.** Both original `Event` rows are untouched, forever. |
| `superseded` | The conflict itself has been superseded by a later analytical artifact (e.g. folded into an Assessment). |

`resolve_conflict()` validates `review_status` against
`CONFLICT_REVIEW_STATUSES` (any other string is a 400), stamps
`resolved_by_user_id`/`resolved_at`/`resolution_note`, and writes its
audit record (`conflict.resolve`, with `prior_status`/`new_status`/
`resolution_note`) in the SAME transaction as the state change -- the
two can never disagree. History is queryable via
`get_review_history()` -> `GET /conflicts/{id}/history`, reusing the
same `AuditRecord` table and `ReviewHistoryEntry` schema the
relationship workflow uses (see `docs/workflows/
ANALYST_REVIEW_WORKFLOW.md`).

## What this does NOT do

Never auto-resolves anything -- `detect_conflicts()` only ever creates
or updates `unresolved` rows; a human decision is the only way
`review_status` changes. Never deletes or edits either underlying
`Event`. Never runs on its own schedule -- `POST /conflicts/detect`
(standalone) and the conflict-detection half of `POST /fusion/run` are
the only two entry points, both explicit and audited. Never treats two
reports from the same source disagreeing with THEMSELVES as a conflict
in a way that differs from two different sources disagreeing -- the
rules above are symmetric regardless of source.

## Tests

`backend/tests/test_identifier_and_conflicts.py` (12 tests):
`test_conflict_detection_requires_an_existing_correlation`,
`test_full_conflict_detection_and_resolution_workflow` (end to end:
detect -> inspect `conflicting_fields` -> resolve as `accepted` ->
verify history), `test_conflict_detection_is_idempotent`,
`test_no_coordinates_on_either_side_is_never_a_spatial_conflict`,
`test_invalid_resolution_status_is_rejected`, plus the six
`identifier_service`-level unit tests the rules above depend on.
