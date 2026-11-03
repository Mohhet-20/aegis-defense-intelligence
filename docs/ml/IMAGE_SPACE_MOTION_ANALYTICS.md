# Image-Space Motion Analytics (Phase 5, Section 7)

`app/tracking/motion.py`'s `compute_motion_summary()` is purely descriptive statistics derived
from a track's own **observed** bounding boxes. Section 7 sets three central prohibitions,
and this module enforces all three by construction -- by simply never computing the forbidden
thing in the first place, not by a flag that could be turned off:

1. **Never a physical-world speed or distance.** Every figure here is in pixels, on the source
   video's own stored frame resolution (`MediaAsset.width_px`/`height_px` -- a real, measured
   property of the file, never a guess or an assumed standard resolution). `unit_note` states
   this explicitly on every response: *"pixels, on the source video's stored frame resolution
   -- never a physical-world unit, never a geographic coordinate."*
2. **Never a geographic coordinate.** There is no latitude/longitude, no map projection, and no
   code path that could produce one from image-space pixel data alone.
3. **Never an interpolated position presented as fact.** A frame with no matched observation
   for a track simply contributes no data point. `compute_motion_summary()` only ever computes
   a `MotionStep` between two **real, observed** points -- never a synthetic one filled in for
   a gap.

## What is computed

- **Per-step displacement** (`MotionStep`): center-to-center pixel displacement between one
  real observation and the **next real observation actually recorded for this track** (which
  may skip several sampled frames if the track went missing in between -- see
  `missing_frame_indices` below), plus elapsed wall-clock seconds and a direction in
  **image-coordinate convention**: 0&deg; = +x (right), 90&deg; = +y (**down** -- screen space,
  not a compass bearing or mathematical convention). Direction is `None`, never fabricated as
  `0.0`, when displacement is exactly zero (a direction is genuinely undefined for a
  stationary object, and `0.0` would falsely imply "moving right").
- **Aggregate path statistics**: total path length (sum of per-step displacements -- not the
  same as net displacement for a non-straight path), net displacement (straight-line,
  first-to-last observation), and bounding-box area at the first and last observation plus
  their ratio (a simple, honest proxy for "object got closer/farther" within one video --
  never translated into a physical distance).
- **Gaps, named explicitly**: given the full list of frame indices the source `InferenceJob`
  actually sampled (`job_sampled_frame_indices`), `missing_frame_indices` lists exactly which
  of those frames, within this track's own observed span, have no observation for it, and
  `fragmentation_count` counts how many separate observed "runs" that span splits into (1 for
  a track with zero gaps). Passing `None` for `job_sampled_frame_indices` skips this
  computation entirely rather than guessing at what "missing" would even mean without it.

## What is deliberately never computed

- **Speed** (pixels/second or any derived unit) -- Section 7 does not require it, and a speed
  figure invites exactly the "this looks like a real measurement" misreading this module is
  built to avoid.
- **A predicted position** -- there is no Kalman filter or any other motion-prediction model in
  this phase (Section 8 was deliberately deferred; see `docs/ml/TRACKER_ADAPTERS.md`). There
  is consequently no "predicted vs. observed" comparison to make, and no field on `MotionStep`
  that could ever hold one.

## A real bug this honesty discipline caught

Building the synthetic evaluation fixture (`app/tracking/synthetic_fixture.py`) with too large
a per-frame displacement relative to box size initially produced a fixture that fragmented
catastrophically against the tracker's own default `min_iou_threshold` -- the fix (reducing
the per-frame step, worked out from the same IoU-vs-displacement arithmetic this module's
`fragmentation_count` is built to surface) is documented in
`docs/implementation/history/PHASE_5_FINAL_REPORT.md`. The module did exactly what it should: it
never silently smoothed over the bad fixture, it reported real fragmentation that pointed
straight at the actual bug.

## Test coverage

`tests/test_tracking_motion.py` covers: an empty observation list, a stationary object (zero
displacement, `direction_degrees is None`), pure horizontal/vertical/diagonal displacement
with the exact expected pixel and degree values, variable (non-uniform) frame intervals,
missing observations correctly reported (never interpolated) with the exact expected
`missing_frame_indices`, fragmentation across multiple observed runs, `job_sampled_frame_indices
= None` skipping gap computation, the `unit_note`'s explicit physical/geographic disclaimers,
and a direct assertion that no `predicted`/`speed`/`predicted_position` field exists anywhere
on `MotionStep`.
