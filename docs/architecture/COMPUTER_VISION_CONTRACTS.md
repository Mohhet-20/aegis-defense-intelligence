# Computer Vision Contracts — Planned (Phase 4–5)

> **Superseded for everything Phase 4 actually built.** As of Phase 4,
> image/video ingestion, the model registry, inference pipelines, and
> the analyst review workspace are REAL, implemented, and tested — see
> `docs/architecture/COMPUTER_VISION_ARCHITECTURE.md` for the as-built
> architecture. This file's historical content below is kept
> **unmodified** (per this project's "document what changed, don't
> quietly drop it" rule) because it still correctly describes what
> remains PLANNED: `TrackIdentifier`/`TrackObservation` (Phase 5
> tracking/re-identification — deliberately NOT built in Phase 4; see
> `docs/ml/VIDEO_FRAME_ANALYSIS.md`'s "What this does NOT do"). Two
> entities named below were resolved differently than originally
> sketched: `MediaProcessingJob` became the real `InferenceJob`
> (`docs/data/` has no separate schema doc for it; see
> `app/models/inference_job.py` and `docs/ml/INFERENCE_PIPELINE.md`) and
> `DetectionRecord` became the real `DetectionResult`
> (`docs/data/DETECTION_RESULT_SCHEMA.md`) — both extended/renamed
> rather than built as a second, parallel concept. `ModelRecord` itself
> was extended in place exactly as this file predicted below ("already
> exists ... unused by any real inference yet"); see
> `docs/ml/MODEL_REGISTRY.md`.

**Original status note (historical, Phase 1): No image/video
processing, inference, tracking, or re-identification code exists in
this repository yet.** This document defines the shapes and principles
Phase 4 (Computer Vision Infrastructure) and Phase 5 (Tracking and
Re-Identification) will implement against, so Phase 1's database
schema and API versioning don't have to be redesigned when that work
starts.

## Why this exists now

Section 12 asks for documented contracts, not a working pipeline, in
this phase — "do not implement an entire unverified tracking pipeline
in this foundation phase." Writing the shape down now means the `Event`/
`Asset`/`Sensor` models Phase 1 already ships can be referenced by a
future `DetectionRecord`/`Track` model without a breaking schema change.

## Planned entities

- **MediaProcessingJob** — a unit of work over one image/video file or
  stream segment: `id`, `source_media_ref`, `model_record_id`, `status`
  (`queued`/`running`/`succeeded`/`failed`), `started_at`,
  `completed_at`, `error_summary`.
- **ModelRecord** (already exists as a Phase 1 model/table, unused by
  any real inference yet) — `name`, `version`, `model_type`,
  `artifact_reference`, `evaluation_metadata`, `status`.
- **DetectionRecord** — one detected object instance: `job_id`,
  `frame_or_timestamp`, `bounding_box`, `class_label`, `confidence`,
  `model_record_id`.
- **TrackIdentifier** — a persistent identity assigned across frames/
  detections by a tracker: `id`, `first_seen_at`, `last_seen_at`,
  `status`.
- **TrackObservation** — one `(TrackIdentifier, DetectionRecord)`
  linkage with its own confidence, distinct from the detection's own
  confidence (a track-assignment can be less certain than the detection
  that fed it).

## Principles binding the future implementation

- A `DetectionRecord`'s confidence is the model's own output confidence.
  A `TrackObservation`'s confidence is the *tracker's* confidence that
  this detection belongs to this track — **these are not the same
  number** and must never be collapsed into one field.
- Every `DetectionRecord`/`TrackIdentifier` carries its `model_record_id`
  — no detection exists without a named, versioned model behind it.
- Re-identification (matching a track to a previously-seen identity) is
  explicitly a **privacy-sensitive** feature: when implemented, it must
  ship with documented limitations, access controls distinct from
  ordinary track viewing, and a clear non-goal statement (it is a
  "possible match" signal for human review, never an automated identity
  determination used to drive an autonomous action — consistent with
  Rule 10's defensive-scope requirement).
- A processing failure (`MediaProcessingJob.status = "failed"`) must be
  visible and queryable, not silently dropped.
- No covert identification or automated harmful decision workflow may
  be built on top of this contract, per Rule 10.

## What Phase 1 does NOT do

No media is uploaded, decoded, or processed. No inference runs. No
`DetectionRecord`/`TrackIdentifier`/`TrackObservation`/
`MediaProcessingJob` tables exist in the Phase 1 migration. `ModelRecord`
exists as a table (seed data creates one placeholder row) but nothing
references it from real inference output, because there is no real
inference yet.
