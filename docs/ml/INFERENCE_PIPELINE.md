# Inference Pipeline (Phase 4)

`app/services/inference_service.py`. Submits and runs one
`InferenceJob` -- image detection (one frame) or bounded video frame
analysis (a sampled sequence) -- against one registered model/adapter.

## Lifecycle

```
pending --(submit)--> running --(success)--> completed
                           \
                            +--(exception)--> failed --(retry, up to 3x)--> pending (new job)
```

Same four-state shape as Phase 2's `IngestionJob` and Phase 3's
`FusionJob` -- no new lifecycle vocabulary invented.

## Execution model -- stated plainly

**This runs synchronously, inside the API request that submits it.**
`submit_inference_job()` creates the `InferenceJob` row, commits it as
`"pending"`, then immediately calls `_run_job()` in the same request/
transaction context, which flips it to `"running"`, does the real work,
and commits the final `"completed"`/`"failed"` state before the HTTP
response is returned. There is **no background worker, no task queue,
no polling** -- the client gets the final job status in the response
to its own `POST /inference/jobs` call. This is the exact same
discipline `ingestion_service.run_ingestion()` and
`fusion_service.run_fusion_job()` already established; Phase 4 does
not pretend to add real async job execution where none exists.

## Submission validation (before any job row is created)

`_resolve_submission()` checks, in order: the media asset exists and
`status == "stored"`; the media type matches the requested
`job_type` (`image_detection` needs an image, `video_frame_analysis`
needs a video); the model exists, is a registered CV model
(`task_type == "object_detection"`), is `active`/`registered`, and
`supports` this media type. Any failure raises
`InferenceSubmissionError` -> HTTP 400, **before** a job row exists --
a bad submission never shows up in job history as a confusing failed
run.

## Idempotency (Section 9)

An optional `idempotency_key` is unique per `(organization_id,
idempotency_key)`. Resubmitting with the same key returns the
**existing** job unchanged, never a duplicate run -- see
`tests/test_image_inference.py::test_duplicate_submission_with_same_idempotency_key_returns_same_job`.

## Failure handling

`_run_job()` wraps the real work in `try/except Exception`. On failure:
`db.rollback()`, re-`merge()` the job (same pattern `fusion_service.py`
uses), set `status="failed"` and `error_message` (truncated to 2000
chars), and commit. A failure is always a real, visible, queryable
outcome -- never swallowed, never reported as success.

## Retry (Section 9, bounded)

`retry_job()` only accepts a job with `status == "failed"`, and only up
to `MAX_RETRIES = 3` (checked against the *original* job's
`retry_count`, which chains through `retried_from_job_id`). A retry
creates a **new** `InferenceJob` row (never mutates the failed one in
place) with `retry_count = job.retry_count + 1` and
`retried_from_job_id = job.id` -- the failed job's own record is
permanent history.
`tests/test_cv_api_integration.py::test_failed_inference_job_can_be_retried_and_retry_is_bounded`
exercises a genuine failure (a model whose `adapter_key` is temporarily
made unresolvable) and a genuine successful retry after it is restored
-- never an injected fake exception.

## Image vs. video

- **Image** (`job_type="image_detection"`): decode the one stored
  image via `cv2.imdecode`, run the adapter once, postprocess, persist.
  `frames_processed` is always exactly 1; every `DetectionResult`'s
  `frame_index`/`frame_timestamp_seconds` is NULL.
- **Video** (`job_type="video_frame_analysis"`): `app/cv/
  video_sampling.sample_frames()` yields a bounded, sequentially-
  decoded set of frames (see `docs/ml/VIDEO_FRAME_ANALYSIS.md`); the
  adapter runs once per sampled frame.

## Parameters -- always recorded, never silently defaulted

`confidence_threshold`, `nms_iou_threshold`, and (video only)
`frame_sample_interval_seconds`/`max_frames` are stamped into
`InferenceJob.parameters` **even when every value came from a
settings default** -- so a `DetectionResult`'s lineage is traceable to
the exact configuration that produced it, not "whatever the default
happened to be at the time" (Section 4's lineage requirement).

## Server-side clamping, not client-side rejection

`max_frames` has **no upper bound** in the request schema
(`app/schemas/inference.py`) -- only `settings.CV_VIDEO_MAX_FRAMES_PER_JOB`
decides the real cap, applied unconditionally by
`submit_inference_job()`'s own `min()`. A client asking for 10,000
frames gets a `200` with the real (smaller) number of frames actually
processed, never a `422`. **This exact bug -- an upper `le=500` on the
schema field, which rejected an over-large request instead of clamping
it -- was found and fixed during this phase's own test-writing pass**
(`tests/test_video_inference.py::test_video_max_frames_request_is_clamped_to_the_configured_ceiling`
failed with a 422 before the fix), the same anti-pattern Phase 3 found
and fixed for `GET /fusion/graph`.

## What this does NOT do

- No background worker/queue -- see "Execution model" above.
- No real concurrency bound across simultaneous requests -- "bounded
  concurrency" here means bounded *work per job*, not a worker-pool
  limit on how many jobs run in parallel. A true async job runner with
  real concurrency control is reasonable follow-up work, not something
  this phase claims to have built.
- No job cancellation endpoint -- a running job runs to completion
  (bounded by the frame/detection caps) or fails; there is nothing to
  cancel mid-flight because nothing runs long enough, by design, to
  need it.
