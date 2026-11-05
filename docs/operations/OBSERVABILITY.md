# Observability

## Health endpoints
| Endpoint | Auth | Meaning |
|---|---|---|
| `GET /api/v1/health/live` | none | The process responds. Touches no dependency. |
| `GET /api/v1/health/ready` | none | Each required dependency reachable (database, media storage, runtimes); 503 if any fails; booleans only. |
| `GET /api/v1/observability/health` | `observability:read` (administrator) | Detail: dependencies, migration status (current/behind), artifact availability per version (no paths), metrics/logging config. Runs no inference. |

## Metrics
In-process registry (no external stack existed). Fixed catalog: `http_requests_total`, `http_request_duration_seconds`, `inference_jobs_total`, `inference_job_duration_seconds`, `mlops_experiment_runs_total`, `mlops_experiment_duration_seconds`, `mlops_review_signals_total`, `mlops_artifact_verifications_total`, `metrics_label_overflow_total`. Unknown metrics/labels are rejected; labels are normalised; each metric is capped at `METRICS_MAX_SERIES_PER_METRIC` series (overflow folds into `other` and is counted); HTTP route labels use the route **template**, never the raw path (`unmatched` for unknown). `GET /observability/metrics` (JSON) and `/observability/metrics/prometheus` need `observability:read`. Counters are **per process**, reset on restart, and are not aggregated across workers. `METRICS_ENABLED=false` turns collection off.

Not measured (and reported as such, never as 0): job queue depth (no queue exists), DB/storage failure counters, host saturation, per-model usage, cross-process aggregation.

`GET /observability/summary` returns organization-scoped daily job/run counts and signal counts; process request metrics are shown only to holders of `observability:read`.

## Logging
`LOG_FORMAT=text` (default, unchanged) or `json` (timestamp, severity, subsystem, environment, request_id, job_id, operation, duration_ms, outcome, error_category). A redaction filter runs in both formats: bearer tokens, JWT-shaped strings, `password=`/`token=`/`api_key=` pairs and any field whose name looks sensitive; long fields are truncated. Request bodies, uploaded media and prompts are not logged. `X-Request-ID` is propagated via a context variable.

## Error classification
Stable categories: validation, authorization, missing_artifact, unsupported_configuration, resource_limit, database, storage, conflict-as-validation, interrupted, internal. Client messages are scrubbed (paths/secrets removed); `MlopsError` responses carry `error_category` and `request_id`.
