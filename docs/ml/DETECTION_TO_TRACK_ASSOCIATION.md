# Detection-to-Track Association (Section 5)

`app/tracking/association.py` is a pure, DB-free module: given the last known box of every
active track and the boxes of every detection in the current frame, it decides which pairs
represent the same object. It has no knowledge of ORM rows, frames before the current one, or
anything beyond the two lists it is handed.

## Why the Hungarian algorithm, not a greedy sort

Section 5 asks for "a tested implementation compatible with the project" when an assignment
algorithm is used. `associate()` builds a cost matrix (`1 - IoU` per track/detection pair) and
solves it with `scipy.optimize.linear_sum_assignment` -- a real, tested library implementation.

This is also a strictly better choice than a hand-rolled greedy row-by-row scan: greedy
matching can lock in a locally-good-looking pair that blocks a globally better one elsewhere
in the same frame, while the Hungarian algorithm finds the assignment that minimizes **total**
cost across every pair simultaneously. `test_tracking_association.py`'s
`test_multiple_pairs_resolved_optimally_not_greedily` constructs exactly this scenario and
confirms the solver picks the globally-optimal pairing.

## IoU, not pixels

`compute_iou(a, b)` is standard intersection-over-union on two `(x_min, y_min, x_max, y_max)`
boxes in the same fractional (0..1) coordinate space `DetectionResult`/`TrackObservation`
already use everywhere else. IoU is scale-invariant, so there is no need to denormalize to
pixels for this comparison -- pixel conversion only happens later, for motion analytics (see
`docs/ml/IMAGE_SPACE_MOTION_ANALYTICS.md`), never for association itself. `compute_iou` never
raises and never divides by zero: a degenerate (zero-area) box or two disjoint boxes both
simply return `0.0`.

## Never forcing a low-confidence match

Section 5's central prohibition: "Never force a match when the association score does not
satisfy the configured criteria." This is enforced as a **post-filter**, not a pre-filter: the
Hungarian solver is first allowed to find its globally optimal assignment over the full cost
matrix (including class-incompatible or low-IoU pairs, which are seeded with a high-but-finite
`forbidden_cost = 10.0` so the solver always prefers any genuinely valid pairing when one
exists). Afterward, every pair the solver actually picked is checked against
`min_iou_threshold` (and, if `require_class_match` is set, the two class labels) -- any pair
that fails either check is **discarded**, and both sides are reported as unmatched. This
two-step shape means a technically "optimal" but still-bad pairing is never silently accepted
just because it was the solver's best available option.

## Class matching

When `require_class_match=True` (the default), a track and a detection with different
`class_label`s are never matched, however high their IoU -- Section 5's "do not merge tracks
based solely on a shared class label" is actually about the inverse risk (merging *because of*
a shared label alone, independent of position), and this module addresses both directions: a
shared label alone is never sufficient (IoU is still required), and a mismatched label alone
is sufficient to block an otherwise-perfect-IoU pair when the config asks for it.
`require_class_match=False` is available for a caller that wants IoU-only matching, but the
tracker's own default configuration keeps class matching on.

## Determinism

For identical inputs and configuration, `associate()`'s result is always identical --
`linear_sum_assignment`'s result is a pure function of the cost matrix, which is itself a pure
function of the inputs. `test_association_is_deterministic_across_repeated_calls` confirms
this directly.

## What this module explicitly does not do

- It does not know about frame history, track lifecycle state, or anything beyond the single
  frame it is handed -- lifecycle logic lives entirely in `app/tracking/trackers/iou_tracker.py`
  (see `docs/ml/TRACK_LIFECYCLE.md`).
- It never fabricates a match to avoid an empty result -- an empty `tracks` or `detections`
  list simply returns every item on the other side as unmatched.
- It never uses appearance, embeddings, or any biometric signal -- only geometric IoU and
  (optionally) the detector's own class label.

## Test coverage

`tests/test_tracking_association.py` covers: a single matching pair, Hungarian-optimal
resolution over multiple ambiguous pairs, no detections, no active tracks, an ambiguous
one-detection/two-track case resolving to exactly one match, a real-but-below-threshold pair
never being forced through, class mismatch under both `require_class_match` settings, and
result determinism across repeated calls with identical input.
