"""Metric normalisation and baseline comparison.

Normalised metric record::

    {"value": float | None, "defined": bool, "reason": str | None,
     "n": int | None,                       # denominator the value is based on
     "ci95": [lo, hi] | None, "ci_method": "wilson" | None,
     "definition": str}

``value`` is None (and ``defined`` False) whenever the metric cannot be computed
-- zero denominator, missing labels/probabilities, etc. -- and is NEVER coerced
to 0. A confidence interval is attached only for plain binomial proportions
(precision, recall, accuracy) where a Wilson interval is justified; it assumes
independent samples. F1, macro-F1, mean IoU, ROC-AUC, Brier and log loss get no
interval because no simple closed form is justified here.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from app.analytics import metrics as base_metrics
from app.core.config import get_settings
from app.core.errors import IncompatibleComparison
from app.mlops.stats import intervals_overlap, wilson_interval

METRIC_IMPL_VERSION = "mlops-1;analytics-" + base_metrics.METRICS_VERSION
LOWER_IS_BETTER = {"brier_score", "log_loss"}
EPS = 1e-9

DEFINITIONS = {
    "precision": "TP / (TP + FP). Undefined when nothing was predicted.",
    "recall": "TP / (TP + FN). Undefined when the data holds no positives.",
    "f1": "2PR / (P + R). Undefined when precision or recall is undefined, or both are 0.",
    "mean_iou": "Mean IoU of matched predictions. Undefined when nothing matched.",
    "accuracy": base_metrics.DEFINITIONS["accuracy"],
    "macro_f1": base_metrics.DEFINITIONS["macro_f1"],
    "roc_auc": base_metrics.DEFINITIONS["roc_auc"],
    "brier_score": base_metrics.DEFINITIONS["brier_score"],
    "log_loss": base_metrics.DEFINITIONS["log_loss"],
}


def rec(value: Optional[float], *, n: Optional[int] = None, reason: Optional[str] = None, ci: Optional[tuple] = None, name: str = "") -> dict:
    defined = value is not None and math.isfinite(value)
    return {
        "value": round(float(value), 6) if defined else None,
        "defined": defined,
        "reason": None if defined else (reason or "undefined"),
        "n": n,
        "ci95": [round(ci[0], 6), round(ci[1], 6)] if (defined and ci) else None,
        "ci_method": "wilson" if (defined and ci) else None,
        "definition": DEFINITIONS.get(name, ""),
    }


def _ratio(num: int, den: int, name: str, why: str) -> dict:
    if den <= 0:
        return rec(None, n=den, reason=why, name=name)
    return rec(num / den, n=den, ci=wilson_interval(num, den), name=name)


def _f1(p: dict, r: dict) -> dict:
    if not p["defined"] or not r["defined"]:
        return rec(None, reason="precision or recall is undefined", name="f1")
    if p["value"] + r["value"] == 0:
        return rec(None, reason="precision and recall are both 0", name="f1")
    return rec(2 * p["value"] * r["value"] / (p["value"] + r["value"]), name="f1")


def detection_metrics(tp: int, fp: int, fn: int, mean_iou_value: Optional[float]) -> dict:
    """Derived from raw counts, not from the legacy run's stored floats (which
    report 0.0 where the quantity is actually undefined)."""
    p = _ratio(tp, tp + fp, "precision", "no predictions were made (TP + FP = 0)")
    r = _ratio(tp, tp + fn, "recall", "the data contains no ground-truth objects (TP + FN = 0)")
    mean_iou = rec(mean_iou_value, n=tp, name="mean_iou") if tp > 0 and mean_iou_value is not None else rec(None, n=tp, reason="no prediction matched a ground-truth box", name="mean_iou")
    return {"precision": p, "recall": r, "f1": _f1(p, r), "mean_iou": mean_iou}


def classification_metrics(report: dict, probability: Optional[dict], positive_label: Optional[str]) -> dict:
    n = report["labelled_sample_count"]
    labels = report["labels"]
    matrix = report["confusion_matrix"]
    correct = sum(matrix[i][i] for i in range(len(labels)))
    out = {"accuracy": _ratio(correct, n, "accuracy", "no labelled samples")}
    mf = report["macro_f1"]
    out["macro_f1"] = rec(mf["value"], n=n, reason=mf.get("reason"), name="macro_f1")
    if positive_label and positive_label in labels:
        i = labels.index(positive_label)
        tp = matrix[i][i]
        predicted = sum(matrix[r][i] for r in range(len(labels)))
        support = sum(matrix[i])
        p = _ratio(tp, predicted, "precision", f"class {positive_label!r} was never predicted")
        r = _ratio(tp, support, "recall", f"class {positive_label!r} does not occur in the labelled data")
        out.update(precision=p, recall=r, f1=_f1(p, r))
    if probability:
        for key in ("roc_auc", "brier_score", "log_loss"):
            m = probability[key]
            out[key] = rec(m["value"], n=probability["scored_sample_count"], reason=m.get("reason"), name=key)
    return out


# ---- thresholds -------------------------------------------------------------
def regression_threshold(task: str, metric: str) -> float:
    cfg = get_settings().mlops_regression_thresholds
    try:
        v = cfg.get(task, {}).get(metric)
        if v is not None and math.isfinite(float(v)) and float(v) >= 0:
            return float(v)
    except (TypeError, ValueError, AttributeError):
        pass
    return get_settings().MLOPS_REGRESSION_ABS_THRESHOLD


def metric_floor(task: str, metric: str) -> Optional[float]:
    cfg = get_settings().mlops_metric_floors
    try:
        v = cfg.get(task, {}).get(metric)
        return float(v) if v is not None and math.isfinite(float(v)) else None
    except (TypeError, ValueError, AttributeError):
        return None


# ---- compatibility ----------------------------------------------------------
_CONFIG_KEYS = {"object_detection": ("iou_match_threshold", "fixture"), "classification": ("labels", "positive_label")}


def compatibility_reasons(base: Any, cand: Any) -> list[str]:
    reasons: list[str] = []
    if base.organization_id != cand.organization_id:
        reasons.append("runs belong to different organizations")
    if base.status != "succeeded" or cand.status != "succeeded":
        reasons.append("both runs must have succeeded")
    if base.task != cand.task:
        reasons.append(f"different tasks ({base.task} vs {cand.task})")
    if (base.dataset_name, base.dataset_version) != (cand.dataset_name, cand.dataset_version):
        reasons.append("different evaluation datasets (name/version)")
    elif base.dataset_fingerprint != cand.dataset_fingerprint:
        reasons.append("same dataset name/version but different dataset fingerprint (the data changed)")
    if base.is_synthetic != cand.is_synthetic:
        reasons.append("one run used a synthetic dataset and the other did not")
    if (base.reproducibility or {}).get("metric_implementation_version") != (cand.reproducibility or {}).get("metric_implementation_version"):
        reasons.append("different metric implementation versions")
    if base.task == cand.task:
        for key in _CONFIG_KEYS.get(base.task, ()):
            if (base.config or {}).get(key) != (cand.config or {}).get(key):
                reasons.append(f"different evaluation setting '{key}'")
    return reasons


def compare_runs(base: Any, cand: Any) -> dict:
    reasons = compatibility_reasons(base, cand)
    if reasons:
        raise IncompatibleComparison(reasons)
    rows = []
    names = [m for m in (cand.metrics or {}) if m in (base.metrics or {})]
    for name in names:
        b, c = base.metrics[name], cand.metrics[name]
        lower = name in LOWER_IS_BETTER
        row: dict = {
            "metric": name, "direction": "lower_is_better" if lower else "higher_is_better",
            "baseline": {"value": b["value"], "n": b.get("n"), "ci95": b.get("ci95")},
            "candidate": {"value": c["value"], "n": c.get("n"), "ci95": c.get("ci95")},
            "comparable": bool(b["defined"] and c["defined"]),
            "absolute_difference": None, "relative_difference": None, "change": "not_comparable",
            "distinguishable_at_95": None, "exceeds_review_threshold": False,
            "review_threshold": regression_threshold(cand.task, name), "note": None,
        }
        if row["comparable"]:
            diff = c["value"] - b["value"]
            row["absolute_difference"] = round(diff, 6)
            if abs(b["value"]) > EPS:
                row["relative_difference"] = round(diff / abs(b["value"]), 6)
            else:
                row["note"] = "relative difference omitted: baseline value is ~0"
            if abs(diff) <= EPS:
                row["change"] = "unchanged"
            else:
                better = diff < 0 if lower else diff > 0
                row["change"] = "improved" if better else "regressed"
            if b.get("ci95") and c.get("ci95"):
                row["distinguishable_at_95"] = not intervals_overlap(b["ci95"], c["ci95"])
            if row["change"] == "regressed" and abs(diff) > row["review_threshold"]:
                row["exceeds_review_threshold"] = True
        else:
            row["note"] = "at least one value is undefined; no difference is reported (undefined is not treated as 0)"
        rows.append(row)
    counts = {k: sum(1 for r in rows if r["change"] == k) for k in ("improved", "regressed", "unchanged", "not_comparable")}
    return {
        "compatible": True,
        "metrics": rows,
        "summary": {
            **counts,
            "review_recommended": any(r["exceeds_review_threshold"] for r in rows),
            "statement": (f"{counts['improved']} improved, {counts['regressed']} regressed, {counts['unchanged']} unchanged, "
                          f"{counts['not_comparable']} not comparable. This is not an overall verdict: read each metric with its sample size and interval."),
        },
        "caveats": [
            "Confidence intervals (where shown) are Wilson intervals that assume independent samples.",
            "A dataset fingerprint match means the same evaluation data, not that the data represents real-world conditions."
            + (" Both runs used SYNTHETIC data." if cand.is_synthetic else ""),
        ],
    }
