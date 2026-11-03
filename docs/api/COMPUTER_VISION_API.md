# Computer Vision API (Phase 4)

All routes below are mounted under `/api/v1` (see `app/main.py`). Every
route requires authentication; the specific permission required is
noted per route (see `app/core/security.py` for the full role/
permission grant table).

## Media (`app/api/routes/media.py`)

| Route | Permission | Notes |
|---|---|---|
| `POST /media` | `MEDIA_MANAGE` | Multipart upload (`file`). Runs the full validation pipeline in `docs/security/MEDIA_UPLOAD_SECURITY.md` before any row is created. `400` with a specific reason on rejection. Re-uploading identical bytes returns the existing `MediaAsset` (idempotent by content hash). |
| `GET /media` | `MEDIA_READ` | Paginated list, optional `?media_type=image\|video` filter. |
| `GET /media/{id}` | `MEDIA_READ` | Metadata only -- no bytes. |
| `GET /media/{id}/content` | `MEDIA_READ` | **The only route that returns media bytes.** Streams the stored content with its detected (sniffed, not client-claimed) MIME type. |

`MediaAssetResponse` fields: `id`, `media_type`, `status`,
`declared_filename`, `detected_mime_type`, `content_hash`, `byte_size`,
`width_px`/`height_px`, `duration_seconds`/`frame_count`/`fps`
(video only, else `null`), `uploaded_by_user_id`, `created_at`.

## CV model registry (`app/api/routes/cv_models.py`)

| Route | Permission | Notes |
|---|---|---|
| `POST /cv/models` | `MODEL_MANAGE` (admin-only) | `{"name", "version", "adapter_key", "supported_media_types", "status"}`. `400` on an unknown `adapter_key` or media type. Idempotent on `(name, version)`. |
| `GET /cv/models` | `MODEL_READ` | Paginated list -- **CV models only** (`task_type IS NOT NULL`); Phase 1's `demo-risk-scorer` never appears here. |
| `GET /cv/models/{id}` | `MODEL_READ` | |

`CVModelResponse` fields: `id`, `name`, `version`, `task_type`,
`adapter_key`, `supported_media_types`, `status`, `created_at`.

## Inference (`app/api/routes/inference.py`)

| Route | Permission | Notes |
|---|---|---|
| `POST /inference/jobs` | `INFERENCE_RUN` | Submits and **synchronously runs** a job (see `docs/ml/INFERENCE_PIPELINE.md` -- the response already carries the final `completed`/`failed` status, there is nothing to poll). `400` (`InferenceSubmissionError`) if the media asset, model, or media-type match is invalid -- before any job row exists. |
| `GET /inference/jobs` | `INFERENCE_READ` | Paginated, optional `?media_asset_id=` and `?status=` filters. |
| `GET /inference/jobs/{id}` | `INFERENCE_READ` | |
| `GET /inference/jobs/{id}/detections` | `INFERENCE_READ` | Paginated `DetectionResult` rows produced by this specific job. `404` if the job itself doesn't exist/isn't in this organization. |
| `POST /inference/jobs/{id}/retry` | `INFERENCE_RUN` | Only valid for a `failed` job, bounded to 3 retries total (chained via `retried_from_job_id`); `400` otherwise. Creates a **new** job row; the original failed job is permanent history. |

`SubmitInferenceJobRequest`: `media_asset_id`, `model_record_id`,
`job_type` (`"image_detection"` \| `"video_frame_analysis"`),
`confidence_threshold`/`nms_iou_threshold` (optional, settings
default), `frame_sample_interval_seconds`/`max_frames` (video only,
optional -- `max_frames` has **no upper bound** in the schema; the real
ceiling is server-side, see `docs/ml/INFERENCE_PIPELINE.md`),
`idempotency_key` (optional).

`InferenceJobResponse` fields: `id`, `media_asset_id`,
`model_record_id`, `job_type`, `status`, `parameters`,
`frames_processed`, `detections_created`, `retry_count`,
`retried_from_job_id`, `error_message`, `started_at`, `finished_at`,
`created_at`.

## Detections (`app/api/routes/detections.py`)

| Route | Permission | Notes |
|---|---|---|
| `POST /detections/{id}/review` | `DETECTION_REVIEW` | `{"review_status": "confirmed"\|"rejected", "review_note": "..."}`. Stamps `reviewed_by_user_id`/`reviewed_at`. |
| `POST /detections/{id}/promote-to-evidence` | `DETECTION_REVIEW` | `{"title", "summary"}`. **`409`** (`ReviewError`) unless the detection's `review_status == "confirmed"` -- never auto-promotes an unreviewed or rejected detection. Returns the newly created `Evidence` row, with `evidence_type="media_reference"` and `detection_result_id` set, carrying the full lineage back through the job and model. |

## Evaluation (`app/api/routes/evaluation.py`)

| Route | Permission | Notes |
|---|---|---|
| `POST /evaluation/runs` | `EVALUATION_RUN` | `{"model_record_id", "sample_count", "iou_match_threshold"}` (last two optional). `404` if the model doesn't exist; `409` (`UnsupportedRuntimeError`) if its `adapter_key` can't be resolved. Always `is_synthetic=true` in the response -- see `docs/ml/MODEL_EVALUATION.md`. |
| `GET /evaluation/runs` | `EVALUATION_READ` | Paginated, optional `?model_record_id=` filter. |
| `GET /evaluation/runs/{id}` | `EVALUATION_READ` | |

## Health (modified -- `app/api/routes/health.py`)

| Route | Notes |
|---|---|
| `GET /health/live` | Unchanged -- never touches a dependency. |
| `GET /health/ready` | Now `{"database": bool, "media_storage": bool, "model_runtime": bool}`; `503` if any is `false`. See `docs/operations/COMPUTER_VISION_OPERATIONS.md`. |

## Audit logging

Every write route above (`media.upload`/`upload_rejected`,
`cv_model.register`, `inference.submit`/`retry`,
`detection.review`/`promote_to_evidence`, `evaluation.run`) records an
`audit_service.record()` entry with the actor, organization,
target type/id, and a small `context_metadata` payload -- the same
audit discipline every write route in Phases 1-3 already follows; no
new audit mechanism was introduced.

## Error shapes (consistent with earlier phases)

- `400` -- validation failure before any state was created
  (`MediaValidationError`, `InferenceSubmissionError`, a bad
  `adapter_key`/media type on registration).
- `404` -- the referenced id doesn't exist, or exists in a different
  organization (never distinguished from "doesn't exist" -- no
  cross-tenant existence leak).
- `409` -- a state-conflict the request can't resolve itself
  (promoting a non-confirmed detection, evaluating a model whose
  adapter can't be resolved).
