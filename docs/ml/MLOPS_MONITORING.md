# Monitoring, drift and review signals

## Snapshots
`POST /mlops/monitoring/snapshots` (permission `mlops:monitor`) submits up to `MLOPS_MONITOR_MAX_ROWS` records for a window (`reference` or `current`). Only **bounded summaries** are stored: numeric features are binned (on the reference's bin edges for current windows), categorical features keep top-K value counts, plus missing/violation counts and labelled-correct counts. Raw rows are never stored. Windows may not end in the future or exceed 366 days; at most 200 snapshots per model version.

## Four separate questions
| Section | Question | Method | Needs |
|---|---|---|---|
| Data drift | Did inputs change? | PSI per feature (warn 0.10, alert 0.25), missing-rate delta, out-of-range counts, schema-violation rate | reference + ≥ `MLOPS_MONITOR_MIN_SAMPLES` per window |
| Prediction drift | Did outputs change? | PSI of label distribution and confidence histogram | predictions in both windows |
| Performance | Is it measurably less accurate? | Accuracy on labelled samples with Wilson 95% intervals; "lower" only when intervals do not overlap | ≥ `MLOPS_MONITOR_MIN_LABELLED` labelled in both windows |
| Operational | Are jobs failing / slow? | `InferenceJob` rows in the window (failure rate if ≥ `MLOPS_JOB_MIN_SAMPLES`, p50/p95 duration) | detection models only |

Drift is **not** performance degradation. Without labels, performance is reported `not_assessable` with the reason; labels are never inferred or fabricated. With no reference, or too few samples, drift is `not_assessable` — which is different from "no drift". PSI thresholds are conventional rules of thumb, not guarantees.

## Review signals
Raised idempotently (one open/acknowledged row per `(organization, dedup_key)`; repeats increment `occurrence_count`; severity only escalates). A resolved signal that recurs creates a new row. Categories: evaluation_failed, metric_regression, metric_below_floor, artifact_unavailable, evaluation_stale, job_failure_rate, input_schema_violations, insufficient_data, data_drift, prediction_drift, performance_degradation.

Lifecycle: open → acknowledged (optional assignee, must be an active user in the same organization) → resolved (notes required). Acknowledge/resolve need `mlops:review`, and are audited. Nothing auto-resolves. A signal is a prompt to look, never a finding of a real-world condition, and triggers no automatic action. `POST /mlops/signals/scan` (needs `mlops:monitor`) reaps stale runs, flags stale evaluations and checks job failure rates; it is safe to repeat.

## Troubleshooting
| Symptom | Cause / fix |
|---|---|
| Run failed `missing_artifact` | Registered artifact no longer under `MLOPS_ARTIFACT_ROOT`; restore it or register a new version. |
| 422 on comparison | Incompatible runs; read `reasons` (different dataset fingerprint, synthetic flag, etc.). |
| Approval refused | Missing/stale evaluation, open serious signal, or you registered the version (separate approver rule). |
| Drift `not_assessable` | No reference, or fewer than the minimum samples. |
| Metrics empty after restart | Metrics are process-local and reset on restart. |
| File artifact "not configured" | Set `MLOPS_ARTIFACT_ROOT`. |
