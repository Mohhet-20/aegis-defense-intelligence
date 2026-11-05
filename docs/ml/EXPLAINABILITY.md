# Explainability

`app/analytics/explainers.py` defines an `Explainer` protocol and a closed
registry. Each explainer declares which outputs it supports (`check`) and either
returns a faithful explanation or states why it cannot.

| Method key | Applies to | What it shows |
|---|---|---|
| `rule_based_factors` | risk assessments that recorded contributing factors | the factors exactly as recorded |
| `detection_confidence_metadata` | detection results | class, the detector's own confidence, box area fraction, model/adapter. No attribution is run. |
| `linear_feature_contribution` | outputs whose model **declares** `evaluation_metadata.linear_weights` and whose output recorded `feature_values` | exact `weight x value`, sorted by magnitude |
| `shap` | nothing today | always reported unsupported: the `shap` package is not installed and no model exposes an explainable artifact |

## Faithfulness rules

* Only recorded/declared quantities are restated; nothing is estimated.
* Every explanation carries an interpretation note: it explains how the
  **output** was produced, not why anything happened in the world; contributions
  are associations inside the model/rule, not causal effects.
* If no method applies, the response says so (`supported: false`) and lists, for
  every method, whether it applies and why not. The UI shows that limitation.
* Explanations are computed on demand and deterministic; they are not stored, so
  they cannot drift from the output.

## Adding a method

Implement `method_key`, `label`, `explanation_kind`, `check`, `explain`, add it
to `EXPLAINERS`, and add compatibility tests. `check` must raise
`ExplanationUnsupported` rather than approximate.
