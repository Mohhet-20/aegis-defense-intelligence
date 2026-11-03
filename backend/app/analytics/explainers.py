"""Extensible explanation interface.

An `Explainer` declares which model-output types it supports and either
returns a faithful explanation or raises `ExplanationUnsupported` with a
stated reason. The registry is a closed, hand-written allow-list (the
same discipline as the CV adapter and tracker registries).

FAITHFULNESS RULES enforced here:
 * An explanation only restates quantities the model/rule actually
   produced or stored. Nothing is estimated, back-filled or invented.
 * Every explanation carries `explanation_kind` and an
   `interpretation_note`: it describes how the OUTPUT was produced, it is
   NOT a causal claim about the real world and says nothing about
   correlation versus cause in the underlying events.
 * A method that cannot apply (or whose dependency is not installed)
   reports `supported=False` with the reason, rather than producing a
   plausible-looking substitute.
"""
from __future__ import annotations

import importlib.util
from typing import Optional, Protocol

CAUSAL_NOTE = (
    "This explains how the output was produced, not why anything happened in the real world. "
    "Contributions are associations within the model or rule; they are not causal effects."
)


class ExplanationUnsupported(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Explainer(Protocol):
    method_key: str
    label: str
    explanation_kind: str  # "rule_based" | "model_metadata" | "feature_attribution"

    def check(self, output: dict) -> None: ...  # raises ExplanationUnsupported
    def explain(self, output: dict) -> dict: ...


class RuleBasedFactorsExplainer:
    """Transparent rule-based explanation: restates the contributing
    factors the rule itself recorded for a risk assessment output."""
    method_key = "rule_based_factors"
    label = "Transparent rule-based factors"
    explanation_kind = "rule_based"

    def check(self, output: dict) -> None:
        if output["output_type"] != "risk_assessment":
            raise ExplanationUnsupported("Rule-based factors apply only to risk-assessment outputs that record contributing factors.")
        if not output.get("features", {}).get("contributing_factors"):
            raise ExplanationUnsupported("This output recorded no contributing factors, so there is nothing faithful to show.")

    def explain(self, output: dict) -> dict:
        factors = output["features"]["contributing_factors"]
        return {"items": [{"name": str(f.get("name", f.get("factor", f))) if isinstance(f, dict) else str(f),
                           "detail": f if isinstance(f, dict) else None} for f in factors],
                "method_detail": f"Factors exactly as recorded by method '{output['model']['name']}'."}


class DetectionMetadataExplainer:
    """Detection confidence plus model metadata -- no attribution."""
    method_key = "detection_confidence_metadata"
    label = "Detection confidence and model metadata"
    explanation_kind = "model_metadata"

    def check(self, output: dict) -> None:
        if output["output_type"] != "detection_result":
            raise ExplanationUnsupported("Detection metadata applies only to detection results.")

    def explain(self, output: dict) -> dict:
        bbox = output["features"]["bbox"]
        area = (bbox["x_max"] - bbox["x_min"]) * (bbox["y_max"] - bbox["y_min"])
        items = [
            {"name": "class_label", "value": output["prediction"]["label"]},
            {"name": "reported_confidence", "value": output["confidence"], "detail": "The detector's own score for this box; uncalibrated unless the model documents otherwise."},
            {"name": "box_area_fraction", "value": round(area, 6), "detail": "Share of the frame the box covers; very small boxes are usually less reliable."},
            {"name": "model", "value": f"{output['model']['name']} v{output['model']['version']}"},
            {"name": "adapter", "value": output["model"].get("adapter_key")},
        ]
        return {"items": items, "method_detail": "Direct restatement of stored detector output; no attribution method was run, so no per-pixel or per-feature importance is available."}


class LinearWeightsExplainer:
    """Feature importance for models that DECLARE linear weights in their
    registry metadata. contribution_i = weight_i * value_i. Exact for a
    linear model; unsupported otherwise."""
    method_key = "linear_feature_contribution"
    label = "Feature contributions (declared linear model)"
    explanation_kind = "feature_attribution"

    def check(self, output: dict) -> None:
        meta = output.get("model", {}).get("evaluation_metadata") or {}
        weights = meta.get("linear_weights")
        features = (output.get("features") or {}).get("feature_values")
        if not isinstance(weights, dict) or not weights:
            raise ExplanationUnsupported("The registered model does not declare linear weights, so exact feature contributions cannot be computed.")
        if not isinstance(features, dict) or not features:
            raise ExplanationUnsupported("This output did not record the feature values it was computed from.")
        missing = sorted(set(weights) - set(features))
        if missing:
            raise ExplanationUnsupported(f"Feature values are missing for declared weights: {missing}.")

    def explain(self, output: dict) -> dict:
        weights = output["model"]["evaluation_metadata"]["linear_weights"]
        values = output["features"]["feature_values"]
        items = sorted(
            ({"name": k, "value": values[k], "weight": w, "contribution": round(w * values[k], 6)} for k, w in weights.items()),
            key=lambda i: abs(i["contribution"]), reverse=True,
        )
        return {"items": items, "method_detail": "contribution = declared weight x recorded feature value; exact for a linear model, listed by absolute size."}


class ShapExplainer:
    """SHAP is only offered when the `shap` package is importable AND the
    model supplies an explainable artifact; neither is true in this
    deployment today, and the limitation is shown rather than faked."""
    method_key = "shap"
    label = "SHAP"
    explanation_kind = "feature_attribution"

    def check(self, output: dict) -> None:
        if importlib.util.find_spec("shap") is None:
            raise ExplanationUnsupported("The 'shap' package is not installed in this deployment.")
        raise ExplanationUnsupported("No registered model exposes an explainable artifact (callable model + background data) to SHAP yet.")

    def explain(self, output: dict) -> dict:  # pragma: no cover - unreachable until a model supports it
        raise ExplanationUnsupported("SHAP is not available.")


EXPLAINERS: dict[str, Explainer] = {e.method_key: e for e in (
    RuleBasedFactorsExplainer(), DetectionMetadataExplainer(), LinearWeightsExplainer(), ShapExplainer(),
)}


def describe_methods(output: dict) -> list[dict]:
    """Every registered method with whether it applies to this output
    and, if not, why -- the UI shows the limitation instead of hiding it."""
    out = []
    for e in EXPLAINERS.values():
        try:
            e.check(output)
            out.append({"method_key": e.method_key, "label": e.label, "explanation_kind": e.explanation_kind, "supported": True, "limitation": None})
        except ExplanationUnsupported as exc:
            out.append({"method_key": e.method_key, "label": e.label, "explanation_kind": e.explanation_kind, "supported": False, "limitation": exc.reason})
    return out


def explain(output: dict, method_key: Optional[str]) -> dict:
    methods = describe_methods(output)
    if method_key is None:
        chosen = next((m for m in methods if m["supported"]), None)
        if chosen is None:
            return {"supported": False, "method_key": None, "limitation": "No registered explanation method applies to this output.", "available_methods": methods}
        method_key = chosen["method_key"]
    if method_key not in EXPLAINERS:
        raise KeyError(method_key)
    explainer = EXPLAINERS[method_key]
    try:
        explainer.check(output)
    except ExplanationUnsupported as exc:
        return {"supported": False, "method_key": method_key, "label": explainer.label, "limitation": exc.reason, "available_methods": methods}
    body = explainer.explain(output)
    return {
        "supported": True, "method_key": method_key, "label": explainer.label, "explanation_kind": explainer.explanation_kind,
        "items": body["items"], "method_detail": body["method_detail"], "interpretation_note": CAUSAL_NOTE,
        "limitation": None, "available_methods": methods,
    }
