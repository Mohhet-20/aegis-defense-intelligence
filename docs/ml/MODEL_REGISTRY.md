# Model Registry (Phase 4)

Extends `app/models/model_record.py`'s `ModelRecord` table (Phase 1) --
there is no parallel `CVModel` table. `app/services/
model_registry_service.py` is the CV-specific CRUD/listing surface over
it.

## Why extend, not duplicate

Phase 1's `docs/architecture/COMPUTER_VISION_CONTRACTS.md` already
named `ModelRecord` as the future CV registry row: *"ModelRecord
(already exists as a Phase 1 model/table, unused by any real inference
yet)"*. Building a separate `CVModel` table would have ignored that and
duplicated an entity this project's own standing rule forbids
duplicating.

## New columns (all nullable/defaulted -- no backfill required)

| Column | Meaning |
|---|---|
| `task_type` | `"object_detection"` for a CV model; **NULL for everything else**, including the pre-existing seeded `demo-risk-scorer` row, which is untouched in every other respect. `list_cv_models_query()` filters on this column -- a non-CV `ModelRecord` is simply invisible to the CV registry. |
| `adapter_key` | A key into `app/cv/adapters/registry.py`'s `_FACTORIES` map -- **never** a free-form class path, module name, or URL. This is the single choke point that keeps a `ModelRecord` row from ever being able to make this platform import or execute arbitrary code (Section 13). |
| `supported_media_types` | JSON list of `"image"`/`"video"`. Checked by `inference_service._resolve_submission()` before any job is created -- submitting an image job against a video-only model is rejected with a 400, not silently run against the wrong input shape. |

## Registering a model

`POST /api/v1/cv/models` (admin-only -- `MODEL_MANAGE`), or directly via
`model_registry_service.register_cv_model()`. Rejects an unknown
`adapter_key` or an unknown media type with a clear `ValueError` before
anything is written. Idempotent on `(name, version)` -- registering the
same name+version twice returns the existing row.

## What exists today

| Name | Adapter | Real inference? | Media types |
|---|---|---|---|
| `mock-object-detector` | `mock_detector_v1` | No -- deterministic, hash-derived | image, video |
| `opencv-hog-person-detector` | `opencv_hog_person_v1` | **Yes** -- real OpenCV HOG+SVM | image, video |
| `demo-risk-scorer` (Phase 1, unchanged) | n/a (`task_type IS NULL`) | n/a | n/a -- not a CV model at all |

Seeded by `backend/scripts/seed.py`.

## What this does NOT do

- Does not download, build, or manage model weight files -- both
  shipped adapters' "weights" (none, and a bundled SVM respectively)
  already exist inside already-installed Python packages. See
  `docs/ml/MODEL_ADAPTERS.md` for why a downloadable-weights model
  (Ultralytics YOLO) is explicitly NOT registered in this environment.
- Does not version model *artifacts* -- `version` is a free-form string
  an administrator sets, not a content hash of a weights file (there is
  no weights file for either shipped adapter).
- Does not enforce per-role restrictions on *which* registered model an
  analyst may run -- any `active`/`registered` CV model is runnable by
  anyone holding `INFERENCE_RUN`.
