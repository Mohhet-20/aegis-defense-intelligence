# Event Correlation

A deterministic, rule-based, fully-explainable
candidate-relationship detector for analyst review. **This is not a
certainty claim, not a fusion engine, and never a merge of two events
into one.** Advanced probabilistic fusion across sources is explicitly
out of scope here -- that is the job.

Implemented in `app/services/correlation_service.py`, model
`app/models/event_correlation.py`.

## What a correlation IS

A row in `event_correlations` linking two EXISTING, UNCHANGED events
(`event_a_id`, `event_b_id`) with:

- `reasons` -- a list of machine-readable codes explaining exactly why
  the rule fired (never an unexplained score).
- `rule_version` -- which version of the rule logic produced it.
- `temporal_delta_seconds` / `spatial_delta_meters` -- the actual measured
  difference, not a bucketed category.
- `match_strength` -- a documented, bounded 0-1 figure (see below), never
  presented as a probability of truth.
- `review_status` -- `candidate` (produced by a rule run, not yet looked
  at), `confirmed`, or `rejected`. **Only an analyst's explicit review
  action changes this** (`POST /api/v1/correlation/{id}/review`) --
  nothing in `correlation_service.py` promotes a candidate automatically.

Both original events are always independently inspectable afterward;
`recompute()` never writes to an `Event` row.

## The rules

Implemented in `_find_reasons()`. For a candidate pair (bounded to events
within `time_window_seconds` of each other -- see "Scan bound" below):

| Reason code | Fires when |
|---|---|
| `shared_source_id` | both events came from the same `DataSource` |
| `shared_asset_reference` | both events reference the same `asset_id` |
| `compatible_event_type` | the two `event_type` values match (case-insensitive exact match today -- a documented, extensible point, not a fuzzy guess) |
| `temporal_proximity` | `observed_at` difference <= `time_window_seconds` (default 1800 = 30 minutes, configurable per recompute request) |
| `spatial_proximity` | both events have valid (non-null) coordinates and their haversine distance <= `spatial_threshold_meters` (default 500m, configurable) |

A candidate requires **at least `MIN_REASONS_FOR_CANDIDATE = 2`**
independent reasons -- `temporal_proximity` alone (the gatekeeper for even
being compared) is never, by itself, enough. This directly satisfies
Section 14's "never treat repeated copies of the same source report as
independent corroboration": a `shared_source_id` match contributes the
lowest weight toward `match_strength`, and two events sharing ONLY a
source and nothing else never clear the 2-reason bar.

Explicit source relationships (pre-declared trust/lineage between two
sources) and free-form documented attribute matches beyond asset/type are
not implemented -- `reasons` is an extensible list, and
adding a new signal means adding one more check to `_find_reasons()`, not
restructuring the model.

## `match_strength`

A weighted sum of the fired reasons' documented weights
(`REASON_WEIGHTS`), clamped to `[0, 1]`:

```
shared_asset_reference: 0.40
temporal_proximity:     0.25
spatial_proximity:      0.25
compatible_event_type:  0.15
shared_source_id:       0.10
```

This number exists to help an analyst triage a long candidate list, NOT
as a probability of truth, hostile intent, or anything evidentiary.
**Proximity in time and space is never, by itself, used to infer hostile
intent** -- `correlation_service.py` only ever records that two
*observations* are close; interpreting what that means is left entirely
to the analyst.

## Recompute: the one explicit, auditable entry point

`POST /api/v1/correlation/recompute` (permission `CORRELATION_MANAGE`,
administrator/analyst only) calls `correlation_service.recompute()`,
which:

- scans events ordered by `observed_at`, comparing each to later events
  only within `time_window_seconds` (a sliding-window early-break, not a
  full O(n^2) scan of the whole table -- events far apart in time are
  never even compared);
- is **idempotent**: a pair that already has a row for the current
  `rule_version` is skipped, never duplicated (enforced by both an
  in-memory set built from existing rows and the DB's own
  `UniqueConstraint(event_a_id, event_b_id, rule_version)`);
- never runs automatically or on a schedule -- there is no background job
  silently creating correlations. Every recompute is audit-logged
  (`correlation.recompute`) with the exact parameters and result counts.

## Correlation never merges, never asserts

- Two correlated events remain two separate `Event` rows, forever.
- `review_status` starts at `candidate` and is never auto-promoted.
- Circular/self-referential pairs are impossible by construction
  (`event_a_id != event_b_id` is enforced in the loop; a pair is stored
  with a single canonical ordering so `(A,B)` and `(B,A)` are the same
  row, never two).
- Conflicting observations (two correlated events that disagree) are
  fully supported -- correlation only records a relationship exists, not
  that the two events agree.

## Addition: per-event-type window override

`recompute()` gained one new optional parameter,
`time_window_seconds_by_type` (wired from `settings.
fusion_time_window_seconds_by_type`, see
`docs/analytics/TEMPORAL_CORRELATION.md`) -- everything above is
otherwise unchanged. When either side of a pair has an `event_type`
listed in that mapping, the larger of the two sides' windows is used
for that pair's own `temporal_proximity` check instead of the global
default; a type not listed is completely unaffected, and the default
value (`"{}"`) means this is a no-op unless an administrator
configures it. See `backend/tests/test_fusion_and_graph.py::
test_per_event_type_time_window_override_is_actually_consumed`.

## Tested scenarios

`tests/test_correlation.py`: nearby compatible events are flagged;
distant events are never compared at all; a single weak signal
(temporal proximity alone) is correctly excluded; two independent
reasons together do produce a candidate; recompute is idempotent;
correlation never mutates the original events; review requires an
explicit analyst decision; the recompute endpoint's permission gate and
the review endpoint's refusal to accept `"candidate"` as a target status.
