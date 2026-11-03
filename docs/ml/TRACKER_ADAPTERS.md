# Tracker Adapters (Phase 5, Section 4)

## The reusable interface

Every tracker implements the `ObjectTracker` protocol (`app/tracking/trackers/base.py`):

```python
class ObjectTracker(Protocol):
    tracker_key: str
    tracker_version: str
    is_deterministic: bool

    def update(self, frame_index: int, timestamp_seconds: float, detections: list[TrackerDetectionInput]) -> TrackerUpdateResult: ...
    def finalize(self) -> list[FinalizedTrack]: ...
```

`update()` is called once per sampled frame, in strictly increasing `frame_index` order.
`finalize()` is called exactly once after the last frame, closing out every track still
active at sequence end, and is idempotent (a second call returns the same already-finalized
list rather than re-ending anything). `app/services/tracking_service.py` has no
algorithm-specific code anywhere -- it only ever calls through this interface.

## The one tracker this phase ships: `iou_hungarian_v1`

`app/tracking/trackers/iou_tracker.py`'s `IoUHungarianTracker` computes per-frame IoU between
every active track's last known box and every current frame's detections, assigns pairs via
the Hungarian algorithm (`app/tracking/association.py`, a tested `scipy` implementation, never
a hand-rolled greedy sort), then layers the explicit, configurable lifecycle rules in
`docs/ml/TRACK_LIFECYCLE.md` on top of the raw assignment.

### One implementation, two roles -- deliberately, not accidentally

Section 4 asks for both "at least one deterministic fixture tracker for tests" and "at least
one baseline multi-object tracking algorithm." `IoUHungarianTracker` is **both**, not two
separate classes. Given identical inputs and configuration, its output is always
byte-identical: the Hungarian solver is a pure function of the cost matrix, and nothing in
this class uses randomness, wall-clock time, or any other non-deterministic input
(`is_deterministic = True`). Building a second, throwaway "fixture tracker" purely for tests
would have duplicated this same guarantee for zero additional coverage.

### Configuration (`TrackerConfig`)

| Field | Default | Meaning |
|---|---|---|
| `min_iou_threshold` | 0.3 | Below this, a pair is never forced into a match, even if the Hungarian solver picked it as the best available option. |
| `max_missed_frames` | 5 | Consecutive missed frames before a confirmed/missing/reacquired track ends (or a tentative track is rejected). |
| `min_hits_to_confirm` | 2 | Matched observations needed before a tentative track becomes confirmed. |
| `require_class_match` | True | Whether association requires the detection's `class_label` to match the track's own. |
| `max_active_tracks` | 100 | Per-job cap on simultaneously active tracks -- an unmatched detection beyond this cap is dropped, never silently exceeded, and is counted in `TrackerUpdateResult.unmatched_detection_count`. |

All five are recorded on every `TrackingJob.config`, even when every value came from the
settings default -- the same lineage discipline `InferenceJob.parameters` already established.

### Known, documented limitations (never hidden)

- **Pure appearance-free IoU association.** Two objects whose boxes cross paths and overlap
  more with each other than with their own track's recent history can be assigned to each
  other's prior track (an "identity switch"). There is no appearance/embedding model here to
  disambiguate this -- and Section 2 forbids biometric/appearance embeddings anyway, so this is
  an accepted, permanent limitation of this approach, not a gap meant to be closed later with a
  stronger model. The synthetic evaluation fixture's "crossing" sequence demonstrates this
  honestly (see `docs/ml/TRACKING_EVALUATION.md`).
- **No motion prediction.** A track's "last known box" is its most recent **observed** box,
  never a predicted position (Section 8 was deliberately deferred). A fast-moving object that
  leaves its own IoU neighborhood between Phase 4's already-sparse sampled frames may fail to
  re-associate and will instead end one track and start a new one.

## The allow-list (`app/tracking/trackers/registry.py`)

`TrackingJob.tracker_key` is a plain string column. The registry's `_FACTORIES` dict is what
actually turns that string into executable Python -- a key not already present there can
never be executed, regardless of what a client requests. This is the exact same closed
allow-list discipline as Phase 4's `app/cv/adapters/registry.py`, applied to trackers instead
of CV model adapters. Adding a second tracker later means writing a new class against the
`ObjectTracker` protocol and adding one line to this dict -- never touching the service or API
layer.

`available_tracker_keys()`, `get_tracker_version()`, and `get_tracker()` are the only entry
points; an unknown key raises `UnsupportedTrackerError` -- a clean, specific, documented error,
never a bare crash or a silent fallback.

## Health / readiness

`health_service.check_tracker_runtime()` actually imports `scipy.optimize.linear_sum_assignment`
and calls it on a trivial matrix, wired into `/health/ready`'s `tracker_runtime` check. An
available API process is never, by itself, proof that tracking actually works.
