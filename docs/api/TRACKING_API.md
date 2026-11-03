# Tracking API (Phase 5, Section 10)

All routes are under `/api/v1`, and every one requires a bearer token and a specific
`Permission` checked server-side via `require_permission` -- see
`docs/security/TRACKING_DATA_GOVERNANCE.md` for the full authorization matrix.

## Tracking jobs

| Method & path | Permission | Notes |
|---|---|---|
| `GET /tracking/config` | `TRACKING_READ` | Lists available trackers **live from the registry** (never a hard-coded duplicate that could drift), plus the settings defaults. |
| `POST /tracking/jobs` | `TRACKING_RUN` | Submits and **synchronously runs** a tracking job over a completed `video_frame_analysis` InferenceJob's detections. `400` for an unknown `tracker_key`, a source job of the wrong type/status, or a media asset missing measured dimensions. |
| `GET /tracking/jobs` | `TRACKING_READ` | Paginated, filterable by `media_asset_id`/`status`. |
| `GET /tracking/jobs/{id}` | `TRACKING_READ` | `404` if not found or not in the caller's organization. |
| `POST /tracking/jobs/{id}/retry` | `TRACKING_RUN` | `400` unless the job's `status == "failed"` and it has not exceeded `TRACKING_MAX_RETRIES` (3). Creates a brand-new `TrackingJob` row -- never mutates the failed one. |
| `GET /tracking/jobs/{id}/summary` | `TRACKING_READ` | Tracks-by-state counts, mean track duration, total observations -- computed live, never cached. |
| `GET /tracking/jobs/{id}/tracks` | `TRACKING_READ` | Paginated, filterable by `state`. |
| `GET /tracking/jobs/{id}/frames/{frame_index}/tracks` | `TRACKING_READ` | Every `TrackObservation` across every track of this job at exactly that frame -- empty, never an error, for a frame with no observations. |

## Tracks

| Method & path | Permission | Notes |
|---|---|---|
| `GET /tracking/tracks/{id}` | `TRACKING_READ` | |
| `GET /tracking/tracks/{id}/observations` | `TRACKING_READ` | Paginated, filterable by `frame_min`/`frame_max`, ordered by `frame_index` ascending. |
| `GET /tracking/tracks/{id}/motion` | `TRACKING_READ` | Image-space-only motion summary -- see `docs/ml/IMAGE_SPACE_MOTION_ANALYTICS.md`. |

## Annotations

| Method & path | Permission | Notes |
|---|---|---|
| `POST /tracking/tracks/{id}/annotations` | `TRACK_ANNOTATE` | `annotation_type` validated against the fixed allow-list (`422` otherwise); `supersedes_annotation_id` marks the prior row's `superseded_at`, never edits or deletes it. |
| `GET /tracking/tracks/{id}/annotations` | `TRACKING_READ` | Full history, including superseded rows. |

## Evaluation

| Method & path | Permission | Notes |
|---|---|---|
| `POST /tracking/evaluation/runs` | `TRACKING_EVALUATION_RUN` | Runs the configured tracker against the deterministic synthetic fixture. `400` for an unknown `tracker_key`. |
| `GET /tracking/evaluation/runs` | `TRACKING_EVALUATION_READ` | Paginated, filterable by `tracker_key`. |
| `GET /tracking/evaluation/runs/{id}` | `TRACKING_EVALUATION_READ` | |

## Request body shape, submission

```json
POST /api/v1/tracking/jobs
{
  "inference_job_id": "...",
  "tracker_key": "iou_hungarian_v1",
  "min_iou_threshold": 0.3,
  "max_missed_frames": 5,
  "min_hits_to_confirm": 2,
  "require_class_match": true,
  "idempotency_key": "optional-client-key"
}
```

Every numeric override is clamped server-side only at its sanity floor (`ge=0`/`ge=1`) --
there is deliberately no upper bound on `max_missed_frames`/`min_hits_to_confirm` (the same
"clamp, never reject" lesson Phase 3/4 already learned, documented in
`docs/implementation/PROJECT_STATUS.md`), since these are per-job configuration choices, not a
resource bound that needs a server-enforced ceiling.

## Response shape, job

Every `TrackingJobResponse` includes `processing_duration_seconds` as a `@computed_field` --
always derived from `started_at`/`finished_at`, never its own stored column, `None` until the
job has both started and finished.

## Retry and "cancellation"

There is no cancel endpoint, and none is planned for this execution model: a `TrackingJob`
runs synchronously inside the HTTP request that submits it, so there is no separate
in-flight, cancellable state for a cancel call to act on -- the request either has already
returned (nothing left to cancel) or is still executing on the same thread that would have to
receive the cancel call. This is identical to Phase 4's `InferenceJob` and is documented
there, not a Phase 5 regression. Retrying a genuinely `failed` job is the supported recovery
path, bounded at 3 attempts.

## Pagination

Every list endpoint returns `{items, total, page, page_size}` via the same bounded
LIMIT/OFFSET `paginate()` helper every other list endpoint in this codebase uses --
`page_size` is clamped server-side to `settings.MAX_PAGE_SIZE` regardless of what a client
requests.
