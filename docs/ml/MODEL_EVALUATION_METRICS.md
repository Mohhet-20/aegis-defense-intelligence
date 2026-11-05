# Classification and Probability Evaluation

Implemented in `app/analytics/metrics.py`; persisted by
`classification_evaluation_service` as `ClassificationEvaluationRun`.

## Metrics and definitions

| Metric | Definition | Undefined when |
|---|---|---|
| accuracy | correct / labelled samples | no labelled samples |
| precision (per class) | TP / (TP + FP) | class never predicted |
| recall (per class) | TP / (TP + FN) | class absent from labels |
| F1 (per class) | 2PR / (P + R) | precision or recall undefined, or both 0 |
| macro F1 | mean of defined per-class F1; excluded classes are listed | no class has a defined F1 |
| confusion matrix | rows = true, columns = predicted | (empty -> zeros) |
| ROC-AUC | rank-based (Mann-Whitney), ties count 1/2 | either class missing |
| Brier score | mean squared error of P(positive) | no scoreable samples |
| log loss | mean negative log-likelihood, probabilities clipped to [1e-15, 1-1e-15] | no scoreable samples |

Every metric is returned as `{value, defined, reason, definition}`. An
undefined metric has `value: null` and a reason; it is never reported as 0.

## Data handling

* Samples with no true label are **excluded and counted**, never guessed.
* Probabilities must be finite and within [0, 1] (otherwise HTTP 422).
  A missing probability excludes that sample from probability metrics only.
* Class imbalance (largest class >= 90%) and classes with no labelled samples
  produce explicit warnings. Fewer than 30 scoreable samples warns that
  estimates are noisy.
* Limits: 20,000 samples per request; all per-sample sequences must align.

## Provenance and honesty

Each run records model id + **registry version**, dataset name + version +
optional reference, the evaluation configuration, metric definitions, warnings,
and results. `is_synthetic` is a **required declaration**; the API returns a
`performance_claim` that, for synthetic data, states the numbers are not
evidence of real-world performance, and for supplied data limits the claim to
that dataset. A `model_version` that differs from the registry version is
rejected (422).

## Other task types

Detection (P4 `ModelEvaluationRun`) and tracking (P5 `TrackingEvaluationRun`)
evaluations are unchanged; they appear in the same overview list with their own
headline metrics and link to their existing pages. Tracking is evaluated only
by the existing fixture-based method; no new tracking metric was added because
no real ground-truth annotations exist in the repository.
