# Computer Vision Test Strategy

64 new backend tests across 8 files, all actually executed against this
repository's real code (no mocked-out assertions). Full suite: 291 tests (227 pre-existing +
64 new), 91% coverage, zero regressions.

## Test files and what each one actually proves

| File | Tests | Proves |
|---|---|---|
| `tests/test_media_security.py` | 11 | Signature sniffing rejects an unrecognized/mismatched file; duplicate upload is idempotent by content hash; filename path-traversal is sanitized to a bare name; size/dimension/duration limits are real and enforced; a corrupt video container is rejected; `storage._resolve()` refuses to escape the configured root. |
| `tests/test_cv_model_registry.py` | 9 | The adapter allow-list only resolves the two shipped keys and raises a clean error for anything else; `register_cv_model()` rejects an unknown `adapter_key`/media type; registration is idempotent on `(name, version)`; the pre-existing `demo-risk-scorer` row is correctly excluded from the CV listing; the registration API is permission-gated and works end-to-end for an admin. |
| `tests/test_detection_postprocessing.py` | 12 | Every validation rule in `app/cv/postprocessing.py` individually: non-finite numbers rejected, out-of-range confidence rejected, a degenerate box (`x_min >= x_max`) rejected, a box exceeding frame bounds rejected, an unknown class label rejected, below-threshold detections dropped; **real NMS** collapses heavily-overlapping boxes to one but leaves non-overlapping boxes both intact; the per-frame detection cap is enforced; empty input returns empty output cleanly. |
| `tests/test_image_inference.py` | 7 | A full image-detection job runs end-to-end with the mock adapter and produces real, persisted, schema-valid `DetectionResult` rows; the same image produces byte-identical detections across two separate runs (determinism); **the real `OpenCVHOGPersonAdapter` actually runs to completion without crashing** (asserted as "completes, schema-valid output" -- never a specific count, per the adapter's own documented limitation); duplicate submission with the same `idempotency_key` returns the same job, not a second one; a job/media type mismatch and an unsupported model are both rejected with `400`; a Viewer-role user cannot submit a job. |
| `tests/test_video_inference.py` | 4 | A video job respects the configured `max_frames` cap; the sampling interval controls *exactly* which frame indices are sampled (asserted against known values, not just a count); **the `max_frames` over-large-request-is-clamped-not-rejected behavior** -- this test caught the real `le=500` schema bug described below; a video job submitted against an image-only model is rejected. |
| `tests/test_detection_review_and_evidence.py` | 7 | An `"unreviewed"` detection cannot be promoted (raises `ReviewError`); a `"rejected"` detection cannot be promoted either; a `"confirmed"` detection *can* be promoted, producing a real `Evidence` row with `detection_result_id` set; the same two negative cases are re-verified through the actual HTTP API (`409`); a Viewer-role user cannot review a detection; the review action is recorded in the audit trail. |
| `tests/test_model_evaluation.py` | 7 | An evaluation run is traceable (model id/version/adapter, dataset name/version, `is_synthetic=True` always) and its metrics are all within `[0, 1]`; running the same evaluation twice produces byte-identical results (determinism); F1 is independently recomputed from the returned precision/recall and checked to match (never trusting the stored value blindly); `metrics_detail` carries a real per-sample breakdown; the API is permission-gated and round-trips a run through list/get. |
| `tests/test_cv_api_integration.py` | 7 | `GET /media/{id}/content` returns the **exact original bytes**, not a re-encoded or truncated copy; media listing paginates correctly; a genuinely-failed inference job (an adapter temporarily made unresolvable) can be retried, and retries are bounded at 3; retrying a non-failed job is rejected; `/health/ready` reports `model_runtime`/`media_storage` individually; `/health/live` is confirmed to never touch a dependency (via a check that would otherwise fail if it did); a rejected upload is confirmed to produce an audit record. |

## Deliberately real, not mocked, where it matters

- **NMS**: `cv2.dnn.NMSBoxes()` is called for real in
  `test_nms_reduces_heavily_overlapping_boxes_to_one` -- the test
  constructs genuinely overlapping boxes and asserts the *count* drops
  to one, not that a mocked function was called.
- **The real adapter**: `test_real_opencv_hog_adapter_runs_to_completion_without_crashing`
  actually instantiates `OpenCVHOGPersonAdapter` and runs
  `cv2.HOGDescriptor` inference on a real decoded frame -- this is the
  literal check that would have caught the `opencv-python-headless`
  5.0.0.93 `HOGDescriptor`-removal bug, and did, during development
  (see `docs/ml/MODEL_ADAPTERS.md`).
- **Byte-exact round trip**: `test_media_content_download_round_trips_exact_bytes`
  compares the downloaded response body to the original upload bytes
  with `==`, not a length or hash check alone.
- **Exact frame indices**: `test_video_job_sampling_interval_controls_which_frames_are_used`
  asserts the literal list `[0, 20, 40]` for a known fps/interval
  combination, not merely "some frames were sampled."

## Two real bugs this test-writing pass actually found (not injected)

1. **`opencv-python-headless` 5.0.0.93 removed `cv2.HOGDescriptor`
   entirely.** Found when the readiness-check test failed with a 503
   instead of 200, traced to `check_model_runtime()` raising
   `AttributeError`. Fixed by pinning `opencv-python-headless==4.14.0.94`
   in `backend/requirements.txt`.
2. **`SubmitInferenceJobRequest.max_frames` had an upper schema bound
   (`le=500`) that rejected an over-large request with 422 instead of
   letting the server clamp it**, the same anti-pattern found
   for `GET /fusion/graph`. Found by
   `test_video_max_frames_request_is_clamped_to_the_configured_ceiling`
   failing with `KeyError: 'status'` against a 422 error body. Fixed by
   removing the upper bound from the schema field.

Both are described in full, with root cause and fix, in
`docs/ml/MODEL_ADAPTERS.md` and `docs/ml/INFERENCE_PIPELINE.md`
respectively -- test-writing finding a real defect, not merely
confirming intended behavior, is treated as the point of writing tests
at all in this project, not an embarrassment to omit.

## What this does NOT cover

- No load/performance testing of inference throughput -- out of scope;
  this layer's execution model is explicitly synchronous and
  unoptimized for throughput (see `docs/ml/INFERENCE_PIPELINE.md`).
- No frontend unit/component test suite was added for the 9 new CV
  pages -- verification for the frontend was
  `tsc -b --force` (typecheck), `eslint .` (lint), and `npm run build`
  (production build), all clean, consistent with the verification
  depth of the frontend work. Adding component tests for the
  CV workspace is reasonable follow-up work, not something this layer
  claims to have done.
- No test exercises a second, real deep-learning adapter (e.g.
  Ultralytics YOLO) -- none is installed in this environment; see
  `docs/ml/MODEL_ADAPTERS.md` for why, and the registration procedure
  for adding one later.
