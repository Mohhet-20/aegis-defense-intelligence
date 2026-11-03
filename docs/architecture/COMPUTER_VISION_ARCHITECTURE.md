# Computer Vision Architecture (Phase 4)

**Status: a real, working, tested vertical slice.** This document
replaces `docs/architecture/COMPUTER_VISION_CONTRACTS.md`'s PLANNED
shapes with what actually exists after Phase 4 -- that file is kept,
unmodified in its historical content, with a note at its top pointing
here, per this project's "write down what changed, don't quietly drop
it" rule.

## What this phase delivers

A secure media ingestion pipeline, a model-adapter architecture (one
deterministic mock + one real classical CV model), bounded image and
video object detection, a detection postprocessing/validation layer,
model evaluation against a synthetic fixture, and integration with the
existing Evidence/review-workflow machinery -- never a parallel one.

## Required lineage (Section 4), as actually implemented

```
MediaAsset --> InferenceJob --> ModelRecord (+ parameters snapshot)
     |                              |
     +------------------------------+--> DetectionResult
                                            |
                                   (confirmed only) --> Evidence (media_reference)
                                            |
                                     DetectionResult.review_status
```

Every arrow above is a real foreign key or a real service-level check,
not a convention: `InferenceJob.media_asset_id`/`model_record_id`,
`DetectionResult.inference_job_id`/`media_asset_id`/`model_record_id`,
`Evidence.detection_result_id`. See `docs/data/MEDIA_ASSET_SCHEMA.md`
and `docs/data/DETECTION_RESULT_SCHEMA.md`.

## Reused vs. new (Section 1/2's "do not duplicate existing entities")

| Concept | Decision | Why |
|---|---|---|
| Model registry | **Reused** `ModelRecord` (Phase 1), extended with `task_type`/`adapter_key`/`supported_media_types` | The Phase 1 contract doc already named `ModelRecord` as the future CV model registry row -- a parallel `CVModel` table would have duplicated it. |
| Evidence/review workflow | **Reused** `Evidence` (Phase 3), extended with `detection_result_id` | `EVIDENCE_TYPES` already reserved `media_reference` for exactly this. A detection is never a parallel "assessment" concept. |
| Audit trail | **Reused** `audit_service.record()`/`list_for_target()` (Phase 1) | Same append-only history pattern Phase 3 reused for relationship/conflict/assessment review. |
| Job orchestration pattern | **Reused the shape**, new table (`InferenceJob`) | Follows `IngestionJob`/`FusionJob`'s exact status-lifecycle/rollback-on-failure pattern (see `docs/ml/INFERENCE_PIPELINE.md`) rather than inventing a new one. |
| Media storage/validation | **New** (`app/cv/storage.py`, `app/cv/media_validation.py`) | Nothing in Phases 1-3 stored or validated binary media -- `Evidence.external_reference_uri` deliberately never fetches content. |
| Detection postprocessing/NMS | **New** (`app/cv/postprocessing.py`) | No prior phase had bounding boxes or confidence scores to validate. |
| Model adapters | **New** (`app/cv/adapters/`) | No prior phase ran inference of any kind. |

## Module map

| Module | Owns |
|---|---|
| `app/cv/media_validation.py` | File-signature sniffing, size/dimension checks, filename sanitization. |
| `app/cv/storage.py` | Content-addressed, traversal-safe, non-public filesystem storage. |
| `app/cv/video_sampling.py` | Bounded, sequential video frame sampling. |
| `app/cv/adapters/` | The model-adapter contract, the allow-list registry, the mock and real adapters. |
| `app/cv/postprocessing.py` | Finite-number/bounds/allow-list validation + real NMS. |
| `app/cv/synthetic_eval_fixture.py` | The deterministic synthetic evaluation dataset. |
| `app/services/media_service.py` | The one entry point from uploaded bytes to a `MediaAsset` row. |
| `app/services/model_registry_service.py` | CV-specific CRUD/listing over `ModelRecord`. |
| `app/services/inference_service.py` | Submits and runs an `InferenceJob` (image or video). |
| `app/services/detection_review_service.py` | Analyst review + the one path into Evidence. |
| `app/services/evaluation_service.py` | Real precision/recall/F1/IoU against the synthetic fixture. |

## Execution model (stated plainly, not left implicit)

Exactly like `IngestionJob` (Phase 2) and `FusionJob` (Phase 3), an
`InferenceJob` runs **synchronously inside the API request** that
submits it. There is still no background worker process, message
queue, or scheduler anywhere in this codebase. "Bounded concurrency"
(Section 9) is a bound on the *work* one job can do (frame-sampling
caps, per-frame detection caps), not a limit on how many jobs run at
once. See `docs/ml/INFERENCE_PIPELINE.md`'s "What this does NOT do."

## Tenant isolation

Unchanged from Phase 1-3: modeled (every new table carries
`organization_id`), not enforced at the query-filter level (Phase 14's
job). `ModelRecord` itself remains platform-level, not org-scoped,
unchanged from Phase 1.

## What this phase explicitly does NOT do

- No facial recognition, no biometric identity matching, no automated
  person identification (the real adapter localizes a generic
  person-shaped region; it never identifies who that is).
- No automated hostile-intent classification -- `ALLOWED_CLASS_LABELS`
  (`app/models/detection_result.py`) is a fixed, small allow-list that
  can never contain an interpretive/threat label.
- No autonomous targeting or weapon-control logic of any kind.
- No arbitrary remote model-weight download at request time (the real
  adapter's weights ship inside the already-installed
  `opencv-python-headless` package).
- No arbitrary code execution from an uploaded file (uploads are only
  ever decoded by Pillow/OpenCV's image/video decoders).
- No unrestricted remote media fetching (media only ever arrives via
  direct multipart upload).
- No continuous real-time surveillance and no cross-camera
  re-identification (Phase 5's job, not this one) -- video analysis is
  bounded, point-in-time frame sampling only.
- No background worker/job queue (see "Execution model" above).
- Tracking, `TrackIdentifier`, and `TrackObservation` remain exactly
  where `COMPUTER_VISION_CONTRACTS.md` left them -- Phase 5, untouched.
