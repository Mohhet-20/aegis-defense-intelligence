# Track Lifecycle (Phase 5, Section 6)

## States

`app/models/track.py`'s `TRACK_STATES`, named deliberately rather than borrowing the
specification's own example vocabulary verbatim (the specification's own wording explicitly
permits this: "adapt these names to the actual implementation ... maintain equivalent clear
semantics"):

| State | Meaning |
|---|---|
| `tentative` | Just created from an unmatched detection; has not yet reached `min_hits_to_confirm`. |
| `confirmed` | Has matched at least `min_hits_to_confirm` observations. |
| `missing` | Confirmed, but has not matched a detection recently (within `max_missed_frames`). |
| `reacquired` | Was `missing`, then matched again before exceeding `max_missed_frames`. |
| `ended` | Exceeded `max_missed_frames`, or the sequence ended, while confirmed/missing/reacquired -- no more observations will ever be added. |
| `rejected` | A tentative track that never confirmed before being abandoned (missed-frame limit, or sequence end) -- kept for transparency, never silently dropped. |

**Deliberately absent, by Section 6's own explicit prohibition:** "destroyed", "captured",
"hostile", or any other label implying a real-world outcome this data never establishes. A
track ending or being rejected is a statement about an *algorithm's bookkeeping*, never about
what happened to a physical object.

## Transitions (`app/tracking/trackers/iou_tracker.py`'s `_TrackState.transition()`)

Every transition is recorded as a `TrackLifecycleEvent {frame_index, timestamp_seconds,
from_state, to_state, reason}`, persisted on `Track.lifecycle_events` (a JSON list, not a 6th
table -- see `docs/data/TRACKING_RESULT_SCHEMA.md` for why). The real transition graph, as
implemented:

```
(new detection) --> tentative
tentative --[reaches min_hits_to_confirm]--> confirmed
tentative --[exceeds max_missed_frames without confirming]--> rejected
tentative --[sequence ends without confirming]--> rejected
confirmed --[no match this frame]--> missing
missing --[matches again]--> reacquired
missing --[exceeds max_missed_frames]--> ended
reacquired --[matches again]--> confirmed
reacquired --[exceeds max_missed_frames]--> ended
confirmed/missing/reacquired --[sequence ends]--> ended
```

A track that never leaves `tentative` and the sequence simply ends is `rejected`, not
`ended` -- "ended" would misleadingly imply it was once confirmed.

## Gaps and reacquisition -- never interpolated

A "gap" is a run of missed frames between two real, matched observations. This platform never
fabricates a position for a missed frame: when a track is `missing`, it simply has no
`TrackObservation` row for the frames it missed. The gap is fully reconstructable after the
fact from `Track.lifecycle_events` plus the track's own (sparse) `TrackObservation` rows --
nothing about it is silently discarded, and nothing about it is silently filled in. See
`docs/ml/IMAGE_SPACE_MOTION_ANALYTICS.md`'s `missing_frame_indices`/`fragmentation_count` for
how this surfaces in motion analytics.

## Sequence-scoped identity, enforced structurally

`Track.sequence_track_id` (e.g. `"track-1"`) carries a `UniqueConstraint` scoped to its own
`tracking_job_id` -- it is unique only within one run, never across jobs, and never reused
within the same job. A retry creates an entirely new `TrackingJob` with its own fresh
numbering starting back at `track-1`. This is a structural guarantee, not a convention: the
database itself would reject a duplicate `sequence_track_id` within one job.

## Class label stability

`Track.class_label` is taken from the track's first matched (or creating) observation and
never changed afterward, even if a later observation in the same track reports a different
label from the underlying detector. A class-label change within one track is a signal worth
surfacing to an analyst (see `TrackAnnotation`'s `false_association`/`uncertain_association`
types), never something this platform silently papers over by overwriting the original label.

## Test coverage

`tests/test_tracking_lifecycle.py` exercises, directly against `IoUHungarianTracker`:
initialization into `tentative`, confirmation after `min_hits_to_confirm`, the
missing-then-reacquired-then-confirmed cycle, termination after exceeding
`max_missed_frames`, a tentative track timing out into `rejected` (not `ended`),
end-of-sequence closing out every remaining state correctly, `finalize()` idempotency,
track-ID uniqueness within one run, and that `update()` rejects both duplicate and
out-of-order `frame_index` values (never silently reordering them).
