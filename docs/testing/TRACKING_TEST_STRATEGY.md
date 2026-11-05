# Tracking Test Strategy (Section 16/17)

## Why a dedicated fixture, not the mock CV adapter pipeline

the `MockDetectionAdapter` derives each detection's box position/size/confidence from a
`sha256` hash of the **entire frame's pixel bytes** -- fine for exercising the own
pipeline, but it means box positions jump unpredictably frame-to-frame when fed the existing
`mp4_bytes` conftest fixture's uniform-color synthetic frames. That is useless for testing
tracking logic, which needs smoothly-moving, predictable boxes to produce a meaningful,
non-fragmented track.

`tests/conftest.py`'s `tracking_source_factory` fixture resolves this by inserting a real
`MediaAsset` + a completed `video_frame_analysis` `InferenceJob`, then **directly inserting**
hand-crafted, smoothly-moving `DetectionResult` rows -- the same kind of controlled
linear-motion construction already proven correct in `app/tracking/synthetic_fixture.py` --
bypassing the mock-adapter image pipeline entirely. This gives persistence/API/security tests
real, predictable, multi-frame detection data to exercise `tracking_service.
submit_tracking_job()` end to end, without being at the mercy of the mock adapter's
hash-based unpredictability. Three named patterns are supported: `"single"` (one object, with
optional `skip_frames` to simulate a detection gap), `"parallel"` (two never-overlapping
objects, a clean multi-object sanity check), and `"crossing"` (two objects that cross and
briefly overlap at a known frame, for identity-switch-adjacent scenarios).

## Test files and what each covers

| File | Category | Covers |
|---|---|---|
| `test_tracking_association.py` | Association | Single/multiple pairs, Hungarian-optimal (not greedy) resolution, no detections, no active tracks, an ambiguous one-detection/two-track case, a real-but-below-threshold pair never forced, class mismatch under both `require_class_match` settings, determinism. |
| `test_tracking_lifecycle.py` | Lifecycle | Initialization into `tentative`, confirmation, missing->reacquired->confirmed, termination after exceeding `max_missed_frames`, a tentative track timing out into `rejected` (not `ended`), end-of-sequence closure, `finalize()` idempotency, track-ID uniqueness, rejection of duplicate/out-of-order `frame_index`, the per-job active-track cap. |
| `test_tracking_motion.py` | Motion | Empty input, stationary object (direction `None`), horizontal/vertical/diagonal displacement with exact expected values, variable frame intervals, missing observations reported (never interpolated), fragmentation across runs, `job_sampled_frame_indices=None` skipping gap computation, the `unit_note`'s disclaimers, absence of any predicted/speed field. |
| `test_tracking_synthetic_fixture.py` | Evaluation fixture | Fixed sequence order and determinism, `parallel` objects never overlapping, `crossing` objects overlapping (IoU &gt; 0.9) exactly at the midpoint frame and not before. |
| `test_tracking_persistence.py` | Persistence | Job/track creation with real counts, observation-to-detection links (mirrored fields match, original detection untouched), a rerun creating an entirely distinct job/track/observation set, a simulated failure rolling back with no orphaned tracks, retry-after-failure succeeding, job list pagination, tenant isolation at the service layer. |
| `test_tracking_security.py` | Security | Viewer/Investigator cannot submit a job (403, `tracking:run` named in the detail); Investigator can read and annotate but not run; Viewer cannot run an evaluation but can read results; an unknown `tracker_key` and a wrong-job-type/nonexistent source job are rejected with a clear 400; an oversized annotation note and an unknown `annotation_type` are rejected with 422; cross-tenant access to a job returns 404. |
| `test_tracking_api.py` | API | Valid submission with real counts and a non-null `processing_duration_seconds`; an invalid source-job reference; job status retrieval; paginated and frame-range-filtered observation history; the per-frame multi-track query; the track motion endpoint's pixel-only response; job summary; the full create-then-supersede annotation workflow; retry correctly rejected for a job that did not fail; the live tracker-config listing. |
| `test_tracking_evaluation.py` | Evaluation | The exact confirmed aggregate metrics against the default-configured baseline tracker; rejection of an unsupported tracker key before anything is persisted; filtering/listing; determinism of repeated runs. |
| `test_health.py` (addition) | Observability | `tracker_runtime` reports `"ok"` in `/health/ready`. |

## What is deliberately not separately tested

- **Predicted-vs-observed motion.** No Kalman/motion-prediction filter exists
  (Section 8 was deliberately deferred), so there is nothing to compare a prediction against.
  `test_no_speed_or_predicted_position_field_exists_on_motion_step` instead confirms this gap
  is real and not an oversight.
- **HOTA/IDF1/MOTA accuracy.** Never computed (no trusted library available) -- see
  `docs/ml/TRACKING_EVALUATION.md`. Only this project's own custom metrics are asserted.
- **Cancellation.** There is no cancel endpoint for a synchronously-executing job -- see
  `docs/api/TRACKING_API.md`'s "Retry and cancellation" section for why this is not a gap to
  close.

## Results, as actually run (not claimed without evidence)

Full backend suite (`pytest -q --cov=app`), including every test alongside the new
Tests above: **368 passed**, **92% statement coverage**. Every new tracking module
(`app/tracking/motion.py`, `app/tracking/trackers/base.py`, `app/tracking/synthetic_fixture.py`)
reaches 100% coverage; `app/tracking/association.py` and `app/tracking/trackers/iou_tracker.py`
reach 99%; the service layer (`tracking_service.py`, `track_annotation_service.py`,
`tracking_evaluation_service.py`) reaches 89-94%.

## Frontend

`tsc -b --force`, `eslint .`, and `npm run build` were all run clean against the new
`pages/tracking/*`, `components/cv/TrackOverlay.tsx`, and the `types/api.ts`/`api/client.ts`
additions. There is
no frontend unit-test harness in this codebase (consistent with every earlier work); frontend
correctness here rests on type-checking, linting, and a clean production build against the
real backend API shapes.
