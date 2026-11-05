# Tracking Evaluation (Section 13)

## Why custom metrics, and not HOTA/IDF1/MOTA

Section 13 permits the standard multi-object-tracking benchmark metrics "only if a correct,
documented implementation or trusted evaluation library is available." Neither exists in this
environment: no `motmetrics`-equivalent package is installed, and hand-rolling one of these
specific, famously easy-to-get-subtly-wrong metrics without a trusted reference to validate
against would risk presenting a confidently wrong number as a real measurement -- exactly the
failure mode this project's "never claim a check passed unless it actually ran, and never
claim a measurement that wasn't honestly computed" discipline exists to prevent.

`app/tracking/evaluation.py` instead computes **simpler, custom-defined** metrics, each with
its own exact definition documented in the module's own docstring (reproduced below), and
every persisted `TrackingEvaluationRun.notes` states plainly that these are not the standard
benchmark metrics of the same or similar names.

## The dataset: a deterministic synthetic fixture, always

No real, labelled, multi-object tracking dataset exists in this repository. Every evaluation
run is against `app/tracking/synthetic_fixture.py`'s two fixed, named, pure-arithmetic
sequences (no `random`, no wall-clock input -- identical output on every run, every machine):

- **`parallel`** -- two objects moving in straight, non-intersecting lines. A tracker with any
  reasonable configuration should track both perfectly. This is the fixture's "easy" sanity
  check.
- **`crossing`** -- two objects moving toward each other so their boxes overlap heavily at the
  exact midpoint frame (constructed with an `assert` confirming the crossing point is exact,
  not approximate). This is a deliberately constructed, honestly-labelled demonstration of the
  baseline tracker's own documented limitation: an appearance-free IoU tracker can legitimately
  swap identities when two objects' boxes overlap more with each other than with their own
  track's recent history.

Every `TrackingEvaluationRun` stamps `is_synthetic=True`, `dataset_name=
"synthetic_parallel_and_crossing_fixture"` -- the same honesty-by-construction pattern
the computer-vision layer's `ModelEvaluationRun` already established.

## Metric definitions (exactly as implemented, in `app/tracking/evaluation.py`)

- **Coverage**: a ground-truth track's coverage by a given predicted track is the fraction of
  the ground-truth track's own frames for which that specific predicted track holds the
  matching observation.
- **Mostly tracked / mostly lost**: a ground-truth track is "mostly tracked" if its single
  best-covering predicted track covers &ge;0.8 of its frames, "mostly lost" if the best
  coverage is &lt;0.2, otherwise "partially tracked" (not separately reported).
- **Track recall**: a ground-truth track is "recalled" if its best-covering predicted track
  covers &ge;0.5 of its frames; `track_recall` is the fraction of ground-truth tracks recalled.
- **Track precision**: a predicted track is a "true positive" if its own observations are
  &ge;0.5 dominated by a single ground-truth identity; otherwise a "false positive" (no real
  correspondence to any one object). `track_precision` is true positives / (true positives +
  false positives).
- **Identity switches**: counted every time a ground-truth track's sequence of covering
  predicted-track-ids changes from one real (non-gap) predicted id to a *different* real
  predicted id.
- **Fragmentation**: for one ground-truth track, (number of distinct predicted tracks that
  ever covered it) - 1, floored at 0; the reported `fragmentation_count` sums this across all
  ground-truth tracks.
- **Mean association IoU**: the mean of `1 - association_cost` across every real (non-`None`
  cost) matched observation the tracker produced.

## Confirmed, real numbers against the default-configured baseline tracker

Hand-verified during development and asserted in `tests/test_tracking_evaluation.py`:
`track_precision=1.0`, `track_recall=1.0`, `identity_switches=2`, `fragmentation_count=2`,
`mostly_tracked_ratio=0.5`, `mostly_lost_ratio=0.0`, `mean_association_iou=0.5`. The two
identity switches and the 0.5 "mostly tracked" ratio come entirely from the `crossing`
sequence's deliberate, documented limitation -- `parallel` alone tracks perfectly (0 switches).
A result of exactly 0 switches overall would mean the fixture itself had regressed (the
crossing no longer actually crosses); a result of many more would mean the tracker itself had
regressed.

## Persistence (`app/services/tracking_evaluation_service.py`)

`run_evaluation()` resolves the tracker version through the same closed allow-list every other
tracking entry point uses (`UnsupportedTrackerError` raised, and nothing persisted, for an
unknown `tracker_key` -- verified by `test_evaluation_rejects_an_unsupported_tracker_key_before_running_anything`),
then persists one `TrackingEvaluationRun` row per call, including a full per-sequence
`metrics_detail` breakdown. Each run is a fresh, independent row -- rerunning the same
configuration never mutates a prior run's result.

## Test coverage

`tests/test_tracking_evaluation.py` and `tests/test_tracking_synthetic_fixture.py` together
cover: the exact expected aggregate metrics above, rejection of an unknown tracker key before
anything is persisted, filtering/listing runs, determinism of repeated evaluation runs, fixture
determinism across calls, the `parallel` sequence's objects never overlapping, and the
`crossing` sequence's objects both staying separated before the midpoint and genuinely
overlapping (IoU &gt; 0.9) exactly at it.
