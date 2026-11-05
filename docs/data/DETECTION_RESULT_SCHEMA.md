# DetectionResult Schema

`app/models/detection_result.py` -- table `detection_results`. One
validated, normalized detected-object instance. Every row here has
already passed `app/cv/postprocessing.py`'s validation (finite numbers,
bounds, allow-listed class label, NMS-deduplicated) before insertion --
this table is the *output* of that validation, not where it happens.

## Schema versioning

`schema_version` (currently `"1.0"`, `DETECTION_SCHEMA_VERSION` in
`app/models/detection_result.py`) is stamped on every row at creation.
A future change to the detection shape (a new required field, a
different coordinate convention) bumps this constant and is expected to
be handled explicitly by any code reading old rows -- never silently
assumed compatible.

## Columns

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `organization_id` | FK -> organizations | |
| `inference_job_id` | FK -> inference_jobs, CASCADE | |
| `media_asset_id` | FK -> media_assets, CASCADE | Denormalized from the job -- avoids a join fan-out on every read (Section 4). |
| `model_record_id` | FK -> model_records, RESTRICT | Denormalized for the same reason; `RESTRICT` so a model can never be deleted out from under detections that cite it. |
| `schema_version` | string | See above. |
| `frame_index` / `frame_timestamp_seconds` | int/float, nullable | **NULL for an image job** (one frame: the image itself). **Always set together for a video job** -- the exact sampled frame, preserved even though the decoded video itself is discarded (`app/cv/video_sampling.py`). |
| `class_label` | string | Must be in `ALLOWED_CLASS_LABELS` -- see "The class-label allow-list" below. |
| `confidence` | float | `CHECK (confidence BETWEEN 0.0 AND 1.0)`. |
| `bbox_x_min`/`bbox_y_min`/`bbox_x_max`/`bbox_y_max` | float | **Fractions of the frame's width/height (0..1), never pixel coordinates.** `CHECK (0 <= x_min < x_max <= 1)` and the same for y. This is what lets the frontend draw a correct overlay at any display size (`components/cv/BoundingBoxOverlay.tsx`) without ever needing to know this table's idea of "pixels." |
| `raw_model_output` | JSON | Adapter-specific extra detail (currently just `{"adapter_key": ...}`) -- informational only, nothing in this platform's own logic depends on it. |
| `review_status` | `"unreviewed"` \| `"confirmed"` \| `"rejected"` | Default `"unreviewed"`. |
| `reviewed_by_user_id` / `reviewed_at` / `review_note` | nullable | Set by `detection_review_service.review_detection()`. |

## The class-label allow-list

`ALLOWED_CLASS_LABELS = ("mock_object", "person", "vehicle",
"unknown_object")` in `app/models/detection_result.py`. This is a
deliberate safety control (Section 13/15), not an oversight: a
detection whose adapter output a label outside this tuple is **rejected
by `app/cv/postprocessing.py` before it is ever persisted** -- it never
becomes a row at all. Adding a new real adapter later means extending
this list deliberately; it is never populated from whatever string a
model happens to emit. In particular, nothing in this list implies
identity, hostile intent, or a weapon/threat classification, and
nothing ever will without a documented, deliberate decision to add it.

## Never auto-promoted

A `DetectionResult` becomes `Evidence` ONLY via
`detection_review_service.promote_to_evidence()`, and only when
`review_status == "confirmed"` -- enforced in code
(`app/services/detection_review_service.py`), not just by convention.
See `docs/workflows/` (via the existing `ANALYST_REVIEW_WORKFLOW.md`
pattern) and `tests/test_detection_review_and_evidence.py`.

## What this does NOT do

- Never stores a pixel crop, thumbnail, or any image data of its own --
  a bounding box is four numbers; the pixels live only in the
  `MediaAsset` this detection references.
- Never collapses `confidence` into any kind of "threat level" or
  interpretive score (Section 13's "five/eight separated evidentiary
  concepts" discipline, carried over).
- Never implies a tracked identity across frames or across media
  assets -- there is no `track_id` column, deliberately (the job).
