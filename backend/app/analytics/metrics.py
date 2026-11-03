"""Classification and probability-estimate metrics.

Pure Python, deterministic, no I/O. Every metric is returned as a
`metric()` dict -- `{"value": float | None, "defined": bool, "reason":
str | None, "definition": str}` -- so an UNDEFINED metric (zero
denominator, a single class present, no samples) is reported as
`value=None` with a stated reason, never silently coerced to 0.0 or 1.0.

Input problems that make the whole computation meaningless (length
mismatch, NaN/inf, probabilities outside [0, 1], non-binary labels for a
probability metric) raise `MetricInputError`; callers map it to a 4xx.
Samples with a missing (None) true label are EXCLUDED and counted
(`excluded_missing_label`), never guessed.
"""
from __future__ import annotations

import math
from typing import Any, Optional, Sequence

METRICS_VERSION = "1.0"

DEFINITIONS = {
    "accuracy": "correct predictions / labelled samples. Misleading under class imbalance; read alongside per-class recall.",
    "precision": "TP / (TP + FP) for one class: of the samples predicted as the class, the fraction that truly are. Undefined when the class is never predicted.",
    "recall": "TP / (TP + FN) for one class: of the samples that truly are the class, the fraction found. Undefined when the class never occurs in the labels.",
    "f1": "2 * precision * recall / (precision + recall). Undefined if either is undefined, or both are zero.",
    "macro_f1": "Unweighted mean of per-class F1 over classes where F1 is defined. Classes with undefined F1 are excluded and listed.",
    "roc_auc": "Probability that a randomly chosen positive sample is scored above a randomly chosen negative one (ties count 1/2). Rank-based; says nothing about calibration. Undefined unless both classes are present.",
    "brier_score": "Mean squared difference between the predicted probability of the positive class and the 0/1 outcome. Lower is better; range 0-1.",
    "log_loss": "Mean negative log-likelihood of the true outcome under the predicted probability (probabilities clipped to [1e-15, 1-1e-15]). Lower is better; unbounded above.",
}
MAX_SAMPLES = 20000
IMBALANCE_WARNING_SHARE = 0.9


class MetricInputError(ValueError):
    """The submitted evaluation data cannot be scored at all."""


def metric(value: Optional[float], *, name: str, reason: Optional[str] = None, digits: int = 6) -> dict:
    defined = value is not None
    return {
        "value": round(float(value), digits) if defined else None,
        "defined": defined,
        "reason": None if defined else (reason or "undefined"),
        "definition": DEFINITIONS.get(name, ""),
    }


def _check_finite(x: Any, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise MetricInputError(f"{what} must be a finite number, got {x!r}")
    return float(x)


def split_labelled(true_labels: Sequence[Any], *others: Sequence[Any]) -> tuple[list, list[list], int]:
    """Drops samples whose true label is None. Returns (kept_true,
    kept_others, excluded_count). Every parallel sequence must have the
    same length as `true_labels`."""
    n = len(true_labels)
    for other in others:
        if len(other) != n:
            raise MetricInputError("all per-sample sequences must have the same length")
    if n > MAX_SAMPLES:
        raise MetricInputError(f"at most {MAX_SAMPLES} samples per evaluation (got {n})")
    keep = [i for i, t in enumerate(true_labels) if t is not None]
    kept_true = [true_labels[i] for i in keep]
    kept_others = [[o[i] for i in keep] for o in others]
    return kept_true, kept_others, n - len(keep)


def confusion_matrix(true_labels: Sequence[str], predicted: Sequence[str], labels: Sequence[str]) -> list[list[int]]:
    """Rows = true class, columns = predicted class, in `labels` order.
    A prediction outside `labels` raises (it would otherwise vanish)."""
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    for t, p in zip(true_labels, predicted):
        if t not in index:
            raise MetricInputError(f"true label {t!r} is not in the evaluation label set {list(labels)}")
        if p not in index:
            raise MetricInputError(f"predicted label {p!r} is not in the evaluation label set {list(labels)}")
        matrix[index[t]][index[p]] += 1
    return matrix


def _per_class(matrix: list[list[int]], labels: Sequence[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i, label in enumerate(labels):
        tp = matrix[i][i]
        fn = sum(matrix[i]) - tp
        fp = sum(matrix[r][i] for r in range(len(labels))) - tp
        precision = tp / (tp + fp) if (tp + fp) > 0 else None
        recall = tp / (tp + fn) if (tp + fn) > 0 else None
        if precision is None or recall is None:
            f1, f1_reason = None, "precision or recall is undefined"
        elif precision + recall == 0:
            f1, f1_reason = None, "precision and recall are both 0"
        else:
            f1, f1_reason = 2 * precision * recall / (precision + recall), None
        out[label] = {
            "support": tp + fn,
            "predicted_count": tp + fp,
            "precision": metric(precision, name="precision", reason="class was never predicted (TP + FP = 0)"),
            "recall": metric(recall, name="recall", reason="class does not occur in the labelled data (TP + FN = 0)"),
            "f1": metric(f1, name="f1", reason=f1_reason),
        }
    return out


def classification_report(true_labels: Sequence[Any], predicted: Sequence[Any], labels: Optional[Sequence[str]] = None) -> dict:
    kept_true, (kept_pred,), excluded = split_labelled(true_labels, predicted)
    for p in kept_pred:
        if p is None:
            raise MetricInputError("predicted_label must not be missing for a labelled sample")
    warnings: list[str] = []
    if excluded:
        warnings.append(f"{excluded} sample(s) had no true label and were excluded from every metric.")

    label_set = list(labels) if labels else sorted({*kept_true, *kept_pred})
    if len(set(label_set)) != len(label_set):
        raise MetricInputError("labels must be unique")

    n = len(kept_true)
    if n == 0:
        warnings.append("No labelled samples: every metric is undefined.")
        empty = metric(None, name="accuracy", reason="no labelled samples")
        return {
            "labels": label_set, "labelled_sample_count": 0, "excluded_missing_label": excluded,
            "confusion_matrix": [[0] * len(label_set) for _ in label_set],
            "accuracy": empty, "macro_f1": metric(None, name="macro_f1", reason="no labelled samples"),
            "per_class": _per_class([[0] * len(label_set) for _ in label_set], label_set),
            "class_distribution": {}, "warnings": warnings,
        }

    matrix = confusion_matrix(kept_true, kept_pred, label_set)
    per_class = _per_class(matrix, label_set)
    correct = sum(matrix[i][i] for i in range(len(label_set)))

    distribution = {label: sum(matrix[i]) for i, label in enumerate(label_set)}
    majority = max(distribution.values())
    if majority / n >= IMBALANCE_WARNING_SHARE and len([c for c in distribution.values() if c > 0]) > 1:
        warnings.append(f"Severe class imbalance: the largest class is {majority / n:.0%} of labelled samples; accuracy is dominated by it.")
    for label, count in distribution.items():
        if count == 0:
            warnings.append(f"Class {label!r} has no labelled samples; its recall is undefined.")

    f1_defined = [(lbl, v["f1"]["value"]) for lbl, v in per_class.items() if v["f1"]["defined"]]
    excluded_classes = [lbl for lbl, v in per_class.items() if not v["f1"]["defined"]]
    macro = sum(v for _, v in f1_defined) / len(f1_defined) if f1_defined else None
    macro_reason = "no class has a defined F1" if macro is None else None
    macro_metric = metric(macro, name="macro_f1", reason=macro_reason)
    macro_metric["excluded_classes"] = excluded_classes

    return {
        "labels": label_set, "labelled_sample_count": n, "excluded_missing_label": excluded,
        "confusion_matrix": matrix, "accuracy": metric(correct / n, name="accuracy"),
        "macro_f1": macro_metric, "per_class": per_class,
        "class_distribution": distribution, "warnings": warnings,
    }


def _binary_outcomes(true_labels: Sequence[Any], positive_label: str) -> list[int]:
    return [1 if t == positive_label else 0 for t in true_labels]


def roc_auc(outcomes: Sequence[int], scores: Sequence[float]) -> dict:
    pos = [s for o, s in zip(outcomes, scores) if o == 1]
    neg = [s for o, s in zip(outcomes, scores) if o == 0]
    if not pos or not neg:
        return metric(None, name="roc_auc", reason="needs at least one positive and one negative labelled sample")
    # Rank-sum (Mann-Whitney U) with average ranks for ties.
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    rank_sum_pos = sum(r for r, o in zip(ranks, outcomes) if o == 1)
    u = rank_sum_pos - len(pos) * (len(pos) + 1) / 2
    return metric(u / (len(pos) * len(neg)), name="roc_auc")


def probability_report(true_labels: Sequence[Any], probabilities: Sequence[Any], positive_label: str) -> dict:
    """Brier score, log loss and ROC-AUC for P(positive_label). Samples
    with a missing true label OR a missing probability are excluded and
    counted separately."""
    n_total = len(true_labels)
    if len(probabilities) != n_total:
        raise MetricInputError("all per-sample sequences must have the same length")
    if n_total > MAX_SAMPLES:
        raise MetricInputError(f"at most {MAX_SAMPLES} samples per evaluation (got {n_total})")
    warnings: list[str] = []
    kept = [(t, p) for t, p in zip(true_labels, probabilities) if t is not None and p is not None]
    missing_label = sum(1 for t in true_labels if t is None)
    missing_prob = sum(1 for t, p in zip(true_labels, probabilities) if t is not None and p is None)
    if missing_label:
        warnings.append(f"{missing_label} sample(s) had no true label and were excluded.")
    if missing_prob:
        warnings.append(f"{missing_prob} labelled sample(s) had no probability from the model and were excluded; none was invented.")

    probs = []
    for _, p in kept:
        pv = _check_finite(p, "probability")
        if not 0.0 <= pv <= 1.0:
            raise MetricInputError(f"probability must be within [0, 1], got {pv}")
        probs.append(pv)
    outcomes = _binary_outcomes([t for t, _ in kept], positive_label)

    result: dict[str, Any] = {
        "positive_label": positive_label, "scored_sample_count": len(kept),
        "excluded_missing_label": missing_label, "excluded_missing_probability": missing_prob,
        "warnings": warnings,
    }
    if not kept:
        reason = "no samples with both a true label and a probability"
        warnings.append("No scoreable samples: every probability metric is undefined.")
        result.update(brier_score=metric(None, name="brier_score", reason=reason),
                      log_loss=metric(None, name="log_loss", reason=reason),
                      roc_auc=metric(None, name="roc_auc", reason=reason))
        return result

    brier = sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(kept)
    eps = 1e-15
    ll = -sum(math.log(min(max(p, eps), 1 - eps)) if o == 1 else math.log(1 - min(max(p, eps), 1 - eps)) for p, o in zip(probs, outcomes)) / len(kept)
    result.update(brier_score=metric(brier, name="brier_score"), log_loss=metric(ll, name="log_loss"), roc_auc=roc_auc(outcomes, probs))
    if len(kept) < 30:
        warnings.append(f"Only {len(kept)} scoreable samples: these estimates are very noisy.")
    if len(set(outcomes)) < 2:
        warnings.append("Only one outcome class is present: ROC-AUC is undefined and Brier/log loss reflect that single class only.")
    return result
