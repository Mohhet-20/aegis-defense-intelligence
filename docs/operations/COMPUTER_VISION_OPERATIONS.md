# Computer Vision Operations (Phase 4, Section 11)

Running this platform's CV subsystem in practice: configuration,
health/readiness, storage disk usage, and the operational gaps stated
honestly rather than hidden.

## Configuration (`app/core/config.py`, mirrored in `backend/.env.example`)

| Setting | Default | Meaning |
|---|---|---|
| `CV_MEDIA_STORAGE_ROOT` | `./media_storage` | Filesystem root for all stored media bytes. **Must be a writable, persistent path** in any real deployment -- this phase does not add object storage (S3-compatible or otherwise); see "What this does NOT do" below. |
| `CV_MAX_IMAGE_UPLOAD_BYTES` | 10 MB | Upload-time size ceiling, image. |
| `CV_MAX_VIDEO_UPLOAD_BYTES` | 75 MB | Upload-time size ceiling, video. |
| `CV_MAX_IMAGE_DIMENSION_PX` | 6000 | Upload-time dimension ceiling, image, per side. |
| `CV_MAX_VIDEO_DIMENSION_PX` | 4000 | Upload-time dimension ceiling, video, per side. |
| `CV_VIDEO_FRAME_SAMPLE_INTERVAL_SECONDS` | 2.0s | Default sampling interval for a video job (a client can request a different one; see `docs/ml/VIDEO_FRAME_ANALYSIS.md`). |
| `CV_VIDEO_MAX_FRAMES_PER_JOB` | 30 | **Always** the real per-job frame ceiling -- server-clamped, never client-overridable past this. |
| `CV_MAX_VIDEO_DURATION_SECONDS` | 600s | Upload-time video duration ceiling. |
| `CV_DEFAULT_CONFIDENCE_THRESHOLD` | 0.35 | Default detection confidence floor, used when a job submission omits it. |
| `CV_DEFAULT_NMS_IOU_THRESHOLD` | 0.45 | Default NMS IoU threshold, same default-only behavior. |
| `CV_MAX_DETECTIONS_PER_FRAME` | 50 | Hard per-frame cap applied in `app/cv/postprocessing.py`, always enforced, not a default. |

Every one of these is a validated `Settings` field (pydantic), not a
bare `os.environ.get()` scattered through the codebase -- the same
discipline every earlier-phase setting in this file already follows.

## Health and readiness (Section 11's liveness/readiness split)

`GET /api/v1/health/live` -- **never** touches a dependency (database,
disk, model runtime). Confirms only that the process is running and
responsive. Unchanged by this phase.

`GET /api/v1/health/ready` -- now reports three independent checks:

```json
{"database": true, "media_storage": true, "model_runtime": true}
```

- `check_media_storage()` (`app/services/health_service.py`) writes,
  reads back, and deletes a small probe file at a dedicated path under
  `CV_MEDIA_STORAGE_ROOT` -- confirms the configured root is actually
  writable right now, not merely that the setting is a non-empty
  string.
- `check_model_runtime()` imports `cv2`, instantiates an
  `HOGDescriptor`, and loads the bundled SVM detector -- the same
  operations `OpenCVHOGPersonAdapter` performs at real inference time
  -- confirming the CV runtime is actually usable in this process, not
  assumed from the package being listed in `requirements.txt`.

If **any** check fails, `/health/ready` returns `503` with the
per-check breakdown still visible in the body, so an operator can see
*which* dependency failed rather than a bare "not ready."

## Disk usage and the storage root

Every unique uploaded file (by content hash, per organization) persists
on disk under `CV_MEDIA_STORAGE_ROOT` forever -- there is no automatic
expiry, retention policy, or cleanup job in this phase. An operator
running this in a long-lived deployment needs to size that volume for
sustained upload volume and monitor its free space directly (no
"storage usage" metric or alert is exposed by this platform itself).
`check_media_storage()`'s probe file is written/read/deleted on every
readiness check and never left behind.

## Logging and observability

Inference jobs, media ingestion, and evaluation runs all go through the
same request-scoped structured logging already established in earlier
phases (no new logging framework introduced). A failed `InferenceJob`
records its `error_message` (truncated to 2000 chars) directly on the
row -- queryable via `GET /inference/jobs/{id}`, not only in logs.

## What this does NOT do

- No object storage (S3/GCS/Azure Blob) integration -- `CV_MEDIA_STORAGE_ROOT`
  is a local (or locally-mounted) filesystem path. A real deployment
  behind a load balancer with multiple API processes needs a shared
  filesystem (e.g. an NFS mount) at that path, or this feature does not
  work correctly across processes -- stated here rather than discovered
  in production.
- No background worker, task queue, or autoscaling story for inference
  jobs -- every job runs synchronously inside its own API request (see
  `docs/ml/INFERENCE_PIPELINE.md`). A deployment expecting to run many
  large video jobs concurrently needs a real async job runner, which
  this phase does not build.
- No retention/expiry policy, quota system, or per-organization storage
  limit on uploaded media -- an organization can upload without bound
  up to each individual file's size/dimension/duration caps.
- No metrics/alerting integration (Prometheus, Datadog, etc.) beyond
  the existing `/health/ready` JSON body -- wiring that up to a real
  monitoring system is deployment-specific follow-up work.
