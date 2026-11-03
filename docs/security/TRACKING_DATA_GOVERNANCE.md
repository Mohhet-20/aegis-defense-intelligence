# Tracking Data Governance (Phase 5, Section 9/15)

## Explicit prohibitions, enforced in code, not just policy

- **No facial recognition, no biometric identification.** Tracks are associated purely on
  geometric IoU between bounding boxes plus (optionally) the detector's own `class_label` --
  `TrackerDetectionInput` (the only shape the tracker ever sees) carries no pixel data, no
  embedding, nothing that could encode a face or biometric signature. See
  `docs/architecture/COMPUTER_VISION_CONTRACTS.md` for the Phase 4 detector-side half of this
  guarantee, which this tracker consumes but never re-derives.
- **No cross-camera or cross-video identity matching.** A `Track` is scoped to exactly one
  `TrackingJob`, which is scoped to exactly one `InferenceJob`, which is scoped to exactly one
  `MediaAsset`. There is no table, column, or code path anywhere that links a track in one job
  to a track in another.
- **No autonomous targeting or weapon-control logic.** This remains a decision-support
  platform end to end -- nothing in `app/tracking/` ever issues a command to any external
  system.
- **No automatic hostile-intent classification.** `Track.state` and `TrackAnnotation.
  annotation_type` are both closed, enumerated allow-lists containing no such value, and
  Section 6's own prohibition against "destroyed"/"captured"/"hostile" labels is enforced by
  never including them in `TRACK_STATES` in the first place.

## Authorization matrix

| Permission | Analyst | Investigator | Viewer | Administrator |
|---|---|---|---|---|
| `TRACKING_RUN` (submit/retry a job) | yes | no | no | yes |
| `TRACKING_READ` (read jobs/tracks/observations/motion) | yes | yes | yes | yes |
| `TRACK_ANNOTATE` (create an annotation) | yes | yes | no | yes |
| `TRACKING_EVALUATION_RUN` | yes | no | no | yes |
| `TRACKING_EVALUATION_READ` | yes | yes | yes | yes |

This mirrors Phase 4's `INFERENCE_RUN` vs. `DETECTION_REVIEW` split exactly: Investigator can
review and annotate but cannot trigger new runs, the same "can look, can flag, cannot spend
compute" boundary already established for detection review. Every route decides this
server-side via `require_permission` -- never a frontend-only check, and the frontend's own
role gates (`canRun`, `canAnnotate` in the Tracking Workspace / Track Detail pages) exist only
to avoid showing a control that would 403, never as the actual enforcement.

## Tenant isolation

Every tracking table carries `organization_id` via `OrgScopedMixin`, and every service
function filters by it (`get_job`, `get_track`, `list_jobs_query`, etc. all take
`organization_id` as a required argument). A request for another organization's job or track
returns `404`, not `403` -- the same "don't even confirm it exists" discipline every other
resource in this codebase follows. `tests/test_tracking_persistence.py`'s tenant-isolation
tests and `tests/test_tracking_security.py`'s cross-tenant-access test both confirm this
directly, at the service layer and the HTTP layer respectively.

## Input validation

- `tracker_key` is checked against the live registry allow-list before a `TrackingJob` row is
  even created (`TrackingSubmissionError`, surfaced as `400`) -- never a dynamic import of an
  arbitrary client-supplied string.
- `annotation_type` is validated twice: once by the Pydantic schema (`422` for an unknown
  value, before the request body is even fully accepted) and again, defensively, by the
  service layer (`AnnotationError`) for any caller that reaches the service directly.
- `TrackAnnotationCreateRequest.note` is capped at 2000 characters (`422` for an oversized
  request) -- the same bound the schema's `max_length` enforces, never silently truncated.
- Numeric tracker-config overrides are floored (`ge=0`/`ge=1`) but never upper-bounded at the
  schema level -- see `docs/api/TRACKING_API.md` for why this is a deliberate choice, not an
  oversight.

## Non-destructive history

`TrackAnnotation` is never edited or deleted once created; a correction creates a new row and
marks the superseded one's `superseded_at`. Nothing in this platform ever rewrites a
`DetectionResult` or a `TrackObservation`'s own mirrored fields after creation -- an
annotation is the only mutable-feeling surface here, and even it only ever grows, never
overwrites.

## Audit

Every state-changing tracking action (`tracking.submit`, `tracking.retry`, `track.annotate`,
`tracking_evaluation.run`) is recorded via `audit_service.record()` with the acting user,
organization, target type/id, outcome, and relevant context metadata -- the same audit
discipline every other mutating action in this codebase follows, queryable via the existing
`/audit` endpoint and `AuditPage`.
