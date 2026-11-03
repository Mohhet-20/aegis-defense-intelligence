# Spatial Correlation

Phase 3, Section 6 (geospatial half). Covers how this codebase uses
distance in TWO different, deliberately different-valued ways: finding
candidates (Phase 2, `correlation_service.py`, unchanged) and flagging
a conflict (Phase 3, `conflict_service.py`, new). Confusing these two
thresholds would be a real correctness bug, so this document exists
specifically to keep them separate.

## The distance calculation (unchanged, Phase 2)

`correlation_service._haversine_meters()` -- the standard great-circle
distance formula over a spherical Earth-radius approximation
(`EARTH_RADIUS_METERS = 6_371_000.0`). Nothing in Phase 3 touches this
function; both the correlation threshold and the (new) conflict
threshold are compared against the exact same distance value computed
once per correlated pair (`EventCorrelation.spatial_delta_meters`).

## Two thresholds, two different jobs

| Threshold | Settings key | Default | Used by | What it means when exceeded |
|---|---|---|---|---|
| Correlation (match) threshold | `FUSION_SPATIAL_THRESHOLD_METERS_DEFAULT` (and Phase 2's own `DEFAULT_SPATIAL_THRESHOLD_METERS`, both 500.0) | 500m | `correlation_service._find_reasons()` | Distance is TOO FAR for `spatial_proximity` to contribute as a positive match signal -- this alone never means the two events disagree, only that proximity didn't help confirm they're related. |
| Conflict threshold | `FUSION_SPATIAL_CONFLICT_THRESHOLD_METERS` | 5000m (10x the match threshold) | `conflict_service._spatial_conflict()` | Distance is far enough that, for two events ALREADY correlated via some OTHER signal (not spatial_proximity itself), the disagreeing locations are now flagged as a real, reportable conflict. |

The conflict threshold is deliberately much LARGER than the match
threshold. If it were the same value, every pair that failed to match
spatially would automatically conflict -- which would make "didn't
correlate on location" indistinguishable from "actively disagrees
about location," collapsing exactly the kind of missing-information-
vs-contradiction distinction Section 9 requires. A 10x gap between the
two (configurable independently) means there's a wide middle band --
"farther apart than the match threshold but closer than the conflict
threshold" -- that is neither a positive spatial signal nor a conflict;
it's simply inconclusive, and inconclusive is not treated as evidence
either way.

## `conflict_service._spatial_conflict()`'s exact guard conditions

A spatial conflict is flagged ONLY when ALL of these hold for an
already-correlated pair:

1. `"spatial_proximity"` is NOT already one of the correlation's own
   `reasons` (if the pair matched spatially, there is by definition no
   spatial disagreement to report).
2. BOTH events have non-null `latitude`/`longitude` -- a missing
   coordinate on either side is unknown, never a conflict
   (`test_no_coordinates_on_either_side_is_never_a_spatial_conflict`).
3. The correlation's own `spatial_delta_meters` is not null (implied by
   #2, but checked explicitly as a defensive guard).
4. That distance exceeds `FUSION_SPATIAL_CONFLICT_THRESHOLD_METERS`
   (or a caller-supplied override on `/conflicts/detect` or
   `/fusion/run`).

## Worked example

Two events, both reporting an asset at `asset-1` (so they correlate via
`shared_asset_reference`, independent of location), 6000m apart:

- Neither fires `spatial_proximity` (6000m > 500m match threshold) --
  this alone changes nothing; `shared_asset_reference` +
  `shared_source_id`/`compatible_event_type` can still clear the
  2-reason minimum and produce a correlation candidate.
- `conflict_service` then sees this already-correlated pair, confirms
  `spatial_proximity` did NOT fire, confirms both sides have real
  coordinates, and 6000m > 5000m (the conflict threshold) -- a
  `location` conflict is recorded with the exact two coordinate pairs
  and the human-readable rule string (`"distance 6000.0m exceeds
  conflict threshold 5000.0m"`).

If the same two events were only 3000m apart instead, neither threshold
would fire: no spatial match signal, and no conflict either -- exactly
the inconclusive middle band described above.

## What this does NOT do

No spatial clustering, heatmaps, or geofencing (Phase 7's job, not this
phase's). No reverse geocoding or named-location resolution -- every
distance here is a raw coordinate-pair calculation, never enriched with
an address or region name. No per-event-type spatial threshold override
(unlike the temporal window -- see `docs/analytics/
TEMPORAL_CORRELATION.md`'s per-type mechanism, which has no spatial
equivalent in this phase). No "this is clearly the same physical
location despite GPS drift" smoothing -- the raw haversine distance is
always what's compared, with no tolerance band beyond the two
documented thresholds above.

## Tests

`backend/tests/test_identifier_and_conflicts.py::
test_no_coordinates_on_either_side_is_never_a_spatial_conflict`
and `test_full_conflict_detection_and_resolution_workflow` (the
`source_severity` case in that test exercises a non-spatial conflict
field, while the module's spatial guard conditions are covered
directly by the "no coordinates" test and by inspection of
`_spatial_conflict()`'s four guard conditions above, each independently
testable). Phase 2's own `test_correlation.py` continues to cover the
match-threshold half (`test_nearby_compatible_events_are_flagged_as_candidates`,
`test_distant_events_are_never_correlated`) unchanged.
