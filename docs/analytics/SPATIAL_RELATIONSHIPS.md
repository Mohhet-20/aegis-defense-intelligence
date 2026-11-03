# Spatial Relationships (Phase 7)

**Status: IMPLEMENTED.** `app/services/spatial_relationship_service.py`,
frontend `pages/geo/SpatialRelationshipExplorerPage.tsx`.

## 1. What a spatial relationship is -- and is not

`generate_candidates()` creates a `"spatially_associated"`
`EvidenceRelationship` row (Phase 3's model; this value was reserved
in `EvidenceRelationship.RELATIONSHIP_TYPES` since Phase 3 and left
unused until this phase) between any `Event`/`Observation` pair that
is **both** within a configurable distance threshold **and** within a
configurable time window of each other.

This is an **explainable proximity association**, never a merge and
never a conflict finding. The relationship's own `explanation` text
says so explicitly: "This is an explainable proximity association
only -- it is NOT a determination that the two records describe the
same real-world event." Determining whether two close records
describe the *same* real-world thing remains Phase 3's
`conflict_service.py`'s job exclusively; `spatial_relationship_service.py`
never calls into it and never produces a `Conflict` row.

## 2. Why Event+Observation, not every pair of record types

Section 11's framing is "two independently-sourced records reporting
activity near the same place/time" -- which maps onto `Event` and
`Observation` (the two record types representing an *occurrence*),
not `Sensor`/`Asset` (fixed infrastructure whose mutual proximity is
a deployment fact already visible on the map, not a new intelligence
finding). `_CANDIDATE_RECORD_TYPES = ("event", "observation")` is a
closed tuple; Sensor<->Sensor and Asset<->* pairs are deliberately
never compared, documented in the module's own docstring rather than
silently absent.

## 3. Bounded pairwise comparison (never O(n^2) in practice)

Section 15 explicitly requires avoiding unbounded pairwise spatial
comparison. `generate_candidates()` bounds this two ways:

1. **Hard ceiling on N**: both record types' usable-location rows are
   fetched oldest-first, capped at
   `settings.GEOSPATIAL_RELATIONSHIP_MAX_CANDIDATES` (1000) combined.
2. **Sliding time window, not a full N^2 scan**: candidates are sorted
   by `observed_at` ascending; for each record `a`, the inner loop
   over later records `b` computes `time_diff = b.timestamp -
   a.timestamp` and **breaks** (not `continue`) the moment
   `time_diff > window_s`, since the list is time-sorted -- nothing
   further in the list can be within the window either. Actual
   distance comparisons (`pairs_considered`) are therefore bounded by
   how many records fall within each other's time window, not by
   N^2, and `pairs_considered` is returned in the response so this is
   verifiable rather than asserted.

Only records whose location is currently classified `"valid"` by
`app/geo/validation.classify_validation_status()` are ever fetched for
comparison (`_usable_rows()`) -- a record with a missing or invalid
location can never produce a spatial-relationship candidate.

## 4. Wrapping an Observation as Evidence (reuse, not duplication)

`EvidenceRelationship.REFERENCEABLE_TYPES = ("event", "evidence")` --
`Observation` is not itself a referenceable type. For an `Observation`
candidate, `_as_relationship_ref()` wraps it as a `"sensor_observation"`
`Evidence` row via `evidence_service.get_or_create_observation_evidence()`
(idempotent -- reuses an already-wrapped `Evidence` row if one
exists). This is the exact pattern Phase 6's
`cross_source_comparison_service.py` established first; that
function's private helper was promoted to a shared, public
`evidence_service` function during this phase specifically so this
module could reuse it rather than duplicating the wrap-or-reuse logic
a second time (see
`docs/architecture/GEOSPATIAL_INTELLIGENCE_ARCHITECTURE.md` Section 2).
`list_candidates()`'s `_resolve_underlying_record()` does the inverse
for display: an `"evidence"` ref that wraps an `Observation` is
reported to the caller as the `Observation` it actually represents,
not as an opaque Evidence id.

## 5. Idempotency and review

`relationship_service.create_relationship()`'s own existing
deduplication means re-running `generate_candidates()` over the same
data never creates a second relationship for an already-known pair --
the response's `candidates_already_known` count reflects this. A
generated candidate is an **ordinary** `EvidenceRelationship` row with
`review_status="candidate"`, `origin="rule_based"` -- reviewed via the
**existing** `POST /relationships/{id}/review` endpoint and
`RELATIONSHIP_READ`/`RELATIONSHIP_MANAGE` permissions, exactly like
any other relationship. No new review endpoint or permission was
added for this (confirmed by
`tests/test_spatial_relationship_service.py::test_candidate_reviewable_via_review_relationship`
and the live Playwright interaction test described in
`docs/implementation/history/PHASE_7_FINAL_REPORT.md`).

## 6. Generation authorization

`POST /geospatial/relationships/generate` requires
`Permission.GEOSPATIAL_MANAGE` (Administrator, Analyst only --
Investigator explicitly excluded, mirroring Phase 3's
`CORRELATION_MANAGE`). `GET /geospatial/relationships` (listing) only
requires the broader `GEOSPATIAL_READ`.

## 7. What this does NOT do

- Never determines or claims two records describe the same real-world
  event -- `conflict_service.py`'s job, never duplicated or called
  into here.
- Never assigns a threat level, priority, or hostile-intent inference
  from proximity -- a candidate's only output is distance, time
  difference, and a plain factual explanation string.
- Never compares Sensor<->Sensor or Asset<->anything pairs.
- Never auto-confirms a generated candidate -- every one starts as
  `review_status="candidate"` and requires an explicit human review
  action to move to `confirmed`/`rejected`/`uncertain`.
- Never deletes or modifies an existing relationship -- re-running
  generation only ever creates new candidates or recognizes already-known
  ones.
