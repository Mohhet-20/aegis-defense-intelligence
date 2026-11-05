# Tracking Operations (Section 11/14)

## Execution model, stated plainly

A `TrackingJob` runs **synchronously inside the API request** that submits it -- there is
still no background worker or message queue anywhere in this codebase. "Bounded concurrency"
here means a bounded amount of *work* per job (the per-job `max_active_tracks` cap; the
already-bounded number of sampled frames inherited from the source `InferenceJob`), not a
worker pool. This is identical to `IngestionJob`/`FusionJob`/`InferenceJob` before it and is
not a regression -- see `docs/ml/INFERENCE_PIPELINE.md`'s own "What this does NOT do" section
for the version of this same honest gap.

A practical consequence: submitting a tracking job over a long video with many sampled frames
holds the HTTP connection open for the whole run. This is an accepted limitation of the
current architecture, carried forward unchanged from every prior job table, not something
Introduces or needs to solve on its own.

## Readiness

`/health/ready` reports a `tracker_runtime` check alongside `database`/`media_storage`/
`model_runtime`: it actually imports `scipy.optimize.linear_sum_assignment` and calls it on a
trivial matrix, never just checking that the package is importable without exercising it.
`/health/live` is untouched -- liveness still never touches the database, filesystem, or any
runtime dependency, so a slow dependency can never make the process look dead.

## Retry policy

A `TrackingJob` can be retried only while `status == "failed"`, and only up to
`TRACKING_MAX_RETRIES` (3) times. A retry always creates a **new** `TrackingJob` row
(`retried_from_job_id` pointing back at the one it retries) -- the failed job's own row is
never mutated, so its original error is preserved for operators to inspect indefinitely, not
overwritten by a later attempt's outcome.

## Failure handling

Every exception during `_run_job()` is caught, the transaction is rolled back
(`db.rollback()` + `db.merge(job)`), and the job is marked `status="failed"` with
`error_category` (the exception's class name) and a truncated `error_message` -- never a
silent swallow, and never a partially-committed set of `Track`/`TrackObservation` rows left
behind from the failed attempt (`tests/test_tracking_persistence.py`'s
`test_a_failed_run_is_recorded_and_rolled_back_without_orphaned_tracks` confirms this
directly).

## Idempotency

An `idempotency_key` supplied on submission is unique per organization (`NULL` never
collides). Resubmitting with the same key returns the **existing** job rather than running a
second time -- the same pattern `InferenceJob` already established.

## Operational limits, all server-enforced

| Limit | Default | Enforced where |
|---|---|---|
| `TRACKING_MIN_IOU_THRESHOLD` | 0.3 | Tracker config -- a per-job override can be supplied but never removed. |
| `TRACKING_MAX_MISSED_FRAMES` | 5 | ditto |
| `TRACKING_MIN_HITS_TO_CONFIRM` | 2 | ditto |
| `TRACKING_MAX_ACTIVE_TRACKS_PER_JOB` | 100 | Tracker itself -- an unmatched detection beyond this cap is dropped and counted, never silently exceeded. |
| `TRACKING_MAX_RETRIES` | 3 | `retry_job()` -- a 4th retry attempt is rejected with a clear `ValueError`. |

## Observability

- `TrackingJob.frames_considered`/`frames_processed`/`detections_considered`/`tracks_created`
  give a real, per-run accounting of exactly what happened -- never estimated after the fact.
- `GET /tracking/jobs/{id}/summary` computes tracks-by-state, mean track duration, and total
  observations live from the database on every call -- never a cached or precomputed figure
  that could drift from the underlying rows.
- Every mutating action is captured in the audit log (see
  `docs/security/TRACKING_DATA_GOVERNANCE.md`).

## Known operational gaps (stated honestly, not hidden)

- No background worker: a very long video (many sampled frames) means a correspondingly long
  synchronous request. Deferred to later work, same as the own gap.
- No horizontal scaling consideration beyond what the underlying FastAPI/SQLite(or configured
  RDBMS) deployment already provides -- this layer adds no new infrastructure.
- No metrics/tracing integration (e.g. OpenTelemetry) -- the audit log and job-row counters
  are the only observability surface today, consistent with every earlier work in this
  codebase.
