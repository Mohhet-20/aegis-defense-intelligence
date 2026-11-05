# Object Tracking Architecture

## What this is, and what it is not

Adds **temporary, sequence-scoped** multi-object tracking on top of the
already-persisted `DetectionResult` rows. A `Track` associates detections across the frames
of exactly one `video_frame_analysis` `InferenceJob` run. It is evidence that a tracking
algorithm linked some detections together within one run -- **never** evidence of a
real-world identity, **never** biometric identification, **never** a claim that two tracks
from two different jobs (or even two reruns of the same video) are "the same object."

Explicitly out of scope, by design, with no code path that could produce them:

- Facial recognition or any biometric identification.
- Cross-camera or cross-video identity matching.
- Autonomous targeting or weapon-control logic.
- Automatic hostile-intent classification.
- A track lifecycle label implying a real-world outcome ("destroyed", "captured", "hostile").

## Where this sits relative to

```
MediaAsset (video) --> InferenceJob (video_frame_analysis, completed)
                              |
                              v
                      DetectionResult (per sampled frame, already validated/NMS'd)
                              |
                              v  (read-only -- never rewritten)
                      TrackingJob --runs--> ObjectTracker (app/tracking/)
                              |
                              v
                      Track --has many--> TrackObservation (mirrors a DetectionResult)
                              |
                              +--> TrackAnnotation (analyst notes, non-destructive)
```

Tracking is **restricted to a source `InferenceJob` of `job_type == "video_frame_analysis"`**
(enforced in `tracking_service._resolve_submission()`). A single `image_detection` job has
exactly one frame -- there is nothing to associate across frames, so building a "tracking job"
over one frame would be a nonsensical, untested code path. This is a deliberate restriction,
not an oversight.

## New tables (5, all new -- no existing table altered)

- `tracking_jobs` -- one run of one tracker over one source `InferenceJob`'s detections.
- `tracks` -- one sequence-scoped association of detections produced by exactly one run.
- `track_observations` -- one frame's link from a `Track` to the `DetectionResult` it matched.
- `track_annotations` -- an analyst's non-destructive note/flag about one track.
- `tracking_evaluation_runs` -- one evaluation of one tracker against the synthetic fixture.

No new "tracker registry" table was built, deliberately mirroring the decision not to
duplicate `ModelRecord` for CV adapters: a tracker is code behind a closed allow-list
(`app/tracking/trackers/registry.py`), never a client-supplied dynamic import. See
`docs/architecture/COMPUTER_VISION_CONTRACTS.md` for the equivalent decision this
one directly mirrors.

## Execution model (stated honestly, not left implicit)

`TrackingJob` runs **synchronously inside the API request** that submits it
(`app/services/tracking_service.submit_tracking_job()` -> `_run_job()`) -- exactly the same
execution model as `IngestionJob`, `FusionJob`, and `InferenceJob` before it. There is still no
background worker or queue anywhere in this codebase. Status reuses the same four-value
vocabulary every prior job table already uses (`pending` / `running` / `completed` / `failed`)
rather than the specification's own example vocabulary (`QUEUED`/`RUNNING`/`SUCCEEDED`) -- Section
1's own instruction to "reuse existing conventions" wins, and the specification's own wording
explicitly allows adapting the names.

Frames are processed one at a time, in strictly increasing `frame_index` order, from the
already-persisted `DetectionResult` rows of the source job -- this service never touches a
video frame's actual pixels. The tracker itself only ever holds state for its own
currently-active tracks, not the whole video's history.

## The pieces, by module

- `app/tracking/association.py` -- pure detection-to-track association (Section 5).
- `app/tracking/trackers/` -- the reusable tracker interface plus one implementation (Section 4).
- `app/tracking/motion.py` -- image-space-only motion analytics (Section 7).
- `app/tracking/synthetic_fixture.py` + `app/tracking/evaluation.py` -- custom-defined tracking
  evaluation against a deterministic synthetic dataset (Section 13).
- `app/services/tracking_service.py` -- orchestration and persistence.
- `app/services/track_annotation_service.py` -- non-destructive analyst annotations.
- `app/services/tracking_evaluation_service.py` -- persistence wrapper around `evaluation.py`.

Each has its own doc: `docs/ml/DETECTION_TO_TRACK_ASSOCIATION.md`, `docs/ml/TRACKER_ADAPTERS.md`,
`docs/ml/TRACK_LIFECYCLE.md`, `docs/ml/IMAGE_SPACE_MOTION_ANALYTICS.md`,
`docs/ml/TRACKING_EVALUATION.md`.

## Authorization

Five new permissions, mirroring the `INFERENCE_RUN`/`DETECTION_REVIEW` split exactly:
`TRACKING_RUN`, `TRACKING_READ`, `TRACK_ANNOTATE`, `TRACKING_EVALUATION_RUN`,
`TRACKING_EVALUATION_READ`. Analyst holds all five; Investigator holds read + annotate + 
evaluation-read (can review, cannot run); Viewer holds read + evaluation-read only. Every
route decides this server-side via `require_permission` -- never a frontend-only check. See
`docs/security/TRACKING_DATA_GOVERNANCE.md`.

## What deliberately does NOT build

- A Kalman filter or any motion-prediction model (Section 8 explicitly permits deferring this
  "if a filter is unnecessary for the baseline tracker ... rather than adding complexity
  without benefit"). A track's "last known box" is always its most recent **observed** box.
- A second tracker implementation. One deterministic tracker (`iou_hungarian_v1`) serves as
  both the project's test fixture and its baseline algorithm -- see `docs/ml/TRACKER_ADAPTERS.md`.
- Any interpolation of a missing position (Section 7's own prohibition).
- HOTA/IDF1/MOTA computation (no trusted library is installed -- see
  `docs/ml/TRACKING_EVALUATION.md`).
- A background worker/queue of any kind.
