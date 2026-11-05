# MLOps architecture

AEGIS extends the existing model registry (`ModelRecord`) and evaluation services instead of adding a parallel system.

## Components
| Concern | Where |
|---|---|
| Registry, immutable versions, lifecycle | `models/model_record.py`, `services/mlops_registry_service.py` |
| Experiments, fingerprints, comparison | `services/mlops_experiment_service.py`, `app/mlops/{fingerprint,compare,stats}.py` |
| Monitoring snapshots, drift | `services/mlops_monitoring_service.py` |
| Review signals | `services/mlops_signal_service.py` |
| Metrics / logs / errors | `core/obs_metrics.py`, `core/logging_config.py`, `core/errors.py` |
| API | `/api/v1/mlops/*`, `/api/v1/observability/*` |
| UI | `/mlops/models`, `/mlops/models/:id`, `/mlops/experiments`, `/mlops/monitoring`, `/mlops/review` |

Services only `flush`; routes commit. `organization_id` always comes from the authenticated user. Other-organization and missing records both return 404.

## Registry and versions
* **Family** is a derived view: versions sharing `name`. There is no family table.
* **Version** = a `ModelRecord` registered through `POST /mlops/models`. It stores `owner_organization_id`, creator, task type, adapter or artifact reference, optional sha256 digest, schema versions, release notes. `(name, version)` is unique (index created by the migration unless legacy duplicates exist).
* **Immutability:** identity columns of owned versions cannot change after insert (ORM `before_update` guard → `ModelImmutableError`). To change a model, register a new version. *Limitation:* legacy rows with no owner (platform-level, pre-original) are visible to every organization and are **not** guarded, because earlier code and tests legitimately edit them.
* **Artifact references:** `adapter:<key>` (closed allow-list) or `artifact:<relative/path>` under `MLOPS_ARTIFACT_ROOT`. URLs, absolute paths, `..`, symlink escapes are rejected; files are only stat'ed/hashed, never loaded or executed. With no root configured, file artifacts are reported *unavailable*, not an error.

## Lifecycle
`registered → review_required → approved → deprecated → archived` (see `TRANSITIONS`).

| Action | Permission |
|---|---|
| request_review | `mlops:review` (analyst, administrator) |
| reject_review, approve, revoke_approval, deprecate, reactivate, archive | `mlops:approve` (administrator) |

Every transition needs a 3–1000 character reason and is written to the append-only `model_lifecycle_events` table and the audit log. **approve / reactivate** additionally require: a succeeded run in the actor's organization, not older than `MLOPS_APPROVAL_MAX_EVAL_AGE_DAYS`; no unresolved serious/critical signal for the version; an approver different from the registrant (`MLOPS_REQUIRE_SEPARATE_APPROVER`). Metrics never approve anything automatically. Deprecate/archive/reactivate also map onto the legacy `status` so new CV inference stops/resumes; history and results are kept.

**"Approved" is registry metadata only.** AEGIS has no serving/activation environment, so no activation or rollback-of-deployment record exists. Rollback is `revoke_approval`/`deprecate`/`reactivate`, each explicit and audited.

## Experiments
Execution is synchronous (no job queue exists): states are `running`, `succeeded`, `failed`. A stale `running` row is marked `failed/interrupted` by the reaper (run on signal scan and on new runs).

* **Detection** runs execute a registered adapter on a built-in *synthetic* fixture (reusing `evaluation_service`). Results describe the fixture only.
* **Classification** runs *score predictions you submit* against your labels (reusing `classification_evaluation_service`). AEGIS does not run your classifier.
* **Idempotency:** same `idempotency_key` + same run fingerprint → 200 with the original run; same key, different payload → 409.
* **Failure safety:** failures are recorded as failed runs with a coarse category and a scrubbed message; earlier results are untouched. Raw stack traces never reach the client.

## Fingerprints and reproducibility
`dataset_fingerprint` = sha256 of canonical JSON of the evaluation data (sample references + ground truth; **not** the predictions). `config_fingerprint` = settings. `run_fingerprint` = model identity + dataset + config + predictions. Canonical JSON sorts keys and rejects NaN/Infinity. Each run stores Python version, platform, library versions, metric-implementation version and (if set) `APP_GIT_COMMIT`.

## Metrics
| Task | Metrics | Notes |
|---|---|---|
| classification | accuracy, macro_f1 (+ precision, recall, f1 for a `positive_label`; brier_score, log_loss if probabilities supplied) | accuracy/precision/recall get a Wilson 95% interval |
| object_detection | precision, recall, f1, mean_iou on the synthetic fixture | |

A metric whose denominator is zero is **undefined** (`value: null`, `defined: false`, with a reason), never 0. No metric is produced without ground truth.

## Fair comparison
`GET /experiments/{id}/comparison[?baseline_run_id=]` compares to the explicitly selected baseline (`PUT /baselines`, per task + dataset name/version). Runs must have the same task, dataset name/version/fingerprint, synthetic flag, metric implementation version and evaluation settings; otherwise **422 with a list of reasons**. The result is per-metric (absolute/relative difference, direction-aware change, interval distinguishability, `exceeds_review_threshold`); there is deliberately **no overall winner**. Thresholds (`MLOPS_REGRESSION_*`, `MLOPS_METRIC_FLOORS_JSON`) only raise review signals.

## Limitations
No model serving/activation; no async jobs/cancellation; classification runs score submitted predictions only; detection evaluation is synthetic only; Wilson intervals assume independent samples; legacy platform-level model rows are not immutable; fingerprints show data identity, not data representativeness.
