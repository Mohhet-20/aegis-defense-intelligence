# Tracking Result Schema (Phase 5, Section 3/9)

Five new tables. No existing Phase 1-4 table is altered.

## `tracking_jobs`

One run of one tracker over the already-persisted `DetectionResult` rows of exactly one
completed `video_frame_analysis` `InferenceJob`.

| Column | Notes |
|---|---|
| `media_asset_id`, `inference_job_id` | FK lineage to the source video and its detection job. |
| `tracker_key`, `tracker_version` | A key into the closed tracker allow-list -- never a dynamic import. |
| `status` | `pending` / `running` / `completed` / `failed` -- same vocabulary as every other job table. |
| `config` | JSON: the exact `min_iou_threshold`/`max_missed_frames`/`min_hits_to_confirm`/`require_class_match`/`max_active_tracks` used, always recorded even when every value came from a settings default. |
| `frames_considered`, `frames_processed`, `detections_considered`, `tracks_created` | Real counts from the actual run. |
| `idempotency_key` | Unique per organization; `NULL` never collides (standard SQL semantics) -- only a client-supplied key dedupes. |
| `retry_count`, `retried_from_job_id` | Self-referencing FK; a retry is always a brand-new row, never a mutation in place. |
| `started_at`, `finished_at` | `processing_duration_seconds` is **never** a stored column -- always derived at read time from these two, so it can never drift from them. |
| `error_category`, `error_message` | Populated only on failure; truncated to 2000 chars, never swallowed. |

## `tracks`

One sequence-scoped association of detections, produced by exactly one `tracking_jobs` run.

| Column | Notes |
|---|---|
| `sequence_track_id` | e.g. `"track-1"` -- `UniqueConstraint(tracking_job_id, sequence_track_id)`. Unique **only within its own job**, structurally enforced, never implied to carry meaning across a rerun. |
| `class_label` | Taken from the first observation, never changed afterward. |
| `first_frame_index`, `last_frame_index`, `first_timestamp_seconds`, `last_timestamp_seconds` | `CheckConstraint(last_frame_index >= first_frame_index)`. |
| `matched_observations_count`, `missed_frames_count` | Real counts, not estimates. |
| `state` | One of `TRACK_STATES` -- see `docs/ml/TRACK_LIFECYCLE.md`. |
| `quality_summary` | JSON: `mean_confidence`, `mean_association_cost`, `fragmentation_count`, `missed_sampled_frame_count`, `bbox_area_px_first/last` -- descriptive only, never a fabricated single "quality score." |
| `lifecycle_events` | JSON list of `{frame_index, timestamp_seconds, from_state, to_state, reason}` -- kept as a column rather than a 6th table, the same "don't over-normalize a first vertical slice" judgment Phase 4 made for `DetectionResult.raw_model_output`. Every gap and reacquisition is reconstructable from this plus the track's own `TrackObservation` rows. |

## `track_observations`

One frame's link from a `Track` to the `DetectionResult` it matched.

| Column | Notes |
|---|---|
| `track_id`, `detection_result_id` (FK `RESTRICT`), `media_asset_id` | `detection_result_id` is `RESTRICT`, not `CASCADE` -- a detection with a tracking observation pointing at it can never be deleted out from under that lineage. |
| `frame_index`, `frame_timestamp_seconds`, `bbox_*`, `class_label`, `confidence` | **Read-only mirrors** of the referenced `DetectionResult` at creation time -- the same denormalize-for-read-convenience judgment Phase 4 made putting `media_asset_id`/`model_record_id` directly on `DetectionResult`. Nothing in this platform ever edits these columns after creation; the original `DetectionResult` row remains the single source of truth. |
| `association_method` | e.g. `"iou_hungarian_v1"` or `"new_track"` for a track's first observation -- never `"unknown"`. |
| `association_cost` | `1 - IoU` for a matched pair, or `NULL` for a track's first observation (there is no prior box to compare against) -- never fabricated when there was no real comparison. |
| `observation_state` | Only ever `"matched"` today (`OBSERVATION_STATES = ("matched",)`). Deliberately **no** `"interpolated"` value exists -- Section 7 forbids silently interpolating a missing position into authoritative evidence, so a frame with no matched detection for a track simply has no row here for that frame/track at all. The column exists (rather than being omitted entirely) so a future, deliberate decision to add a distinguishable display-only interpolated value has somewhere to go without a migration. |

## `track_annotations`

An analyst's note or flag about one track -- never a destructive edit.

`annotation_type` is one of `ANNOTATION_TYPES` (`reviewed`, `possible_error`,
`fragmented_track`, `false_association`, `uncertain_association`, `note`).
`supersedes_annotation_id` + `superseded_at`: correcting an earlier annotation creates a new
row pointing back at the one it supersedes; the old row is marked `superseded_at` but never
edited or deleted -- the same non-destructive history discipline Phase 3 established for
`AssessmentRevision`.

## `tracking_evaluation_runs`

One evaluation of one tracker/configuration against the deterministic synthetic fixture.
Always `is_synthetic=True`. `track_precision`, `track_recall`, `identity_switches`,
`fragmentation_count`, `mostly_tracked_ratio`, `mostly_lost_ratio`, `mean_association_iou` are
real, computed values -- see `docs/ml/TRACKING_EVALUATION.md` for their exact definitions.
`metrics_detail` holds the full per-sequence breakdown.

## Lineage, end to end

```
MediaAsset -> InferenceJob -> DetectionResult -> TrackObservation -> Track -> TrackingJob
```

Every `TrackObservation` carries its own `detection_result_id`; every `Track` carries its own
`tracking_job_id`. An analyst (or this document) can always trace one tracked box all the way
back to the exact detector run, model, and media asset that produced it -- the full lineage
requirement from Section 9, satisfied at both the per-run (`TrackingJob.inference_job_id`) and
per-observation (`TrackObservation.detection_result_id`) granularity.
