"""Hard-coded scenario templates. A template is data only: it names a
registered simulator and supplies default parameter overrides, a question,
and assumptions. Nothing in a template is executed."""
from __future__ import annotations

from . import simulators as S

TEMPLATES: dict[str, dict] = {
    "threshold_sensitivity": {
        "title": "Anomaly threshold vs. measurement noise",
        "simulator_id": "threshold_detection",
        "category": "anomaly_detection",
        "question": "How do precision and recall of a rolling median/MAD detector change with the threshold and the noise level?",
        "params": {"n_points": 400, "noise_sd": 1.0, "outlier_rate": 0.03, "threshold_k": 4.0},
        "assumptions": ["Noise is Gaussian and stationary.", "Outliers are isolated additive spikes of known size."],
    },
    "missing_data_effect": {
        "title": "Effect of missing observations on detection",
        "simulator_id": "threshold_detection",
        "category": "data_quality",
        "question": "How does the detector degrade when a fraction of observations never arrives?",
        "params": {"n_points": 400, "missing_rate": 0.2, "outlier_rate": 0.03},
        "assumptions": ["Observations go missing completely at random."],
    },
    "source_outages": {
        "title": "Source availability and data freshness",
        "simulator_id": "source_availability",
        "category": "source_availability",
        "question": "How fresh is the data when sources suffer random outages and delays?",
        "params": {"n_sources": 3, "duration_hours": 24.0, "failure_rate_per_hour": 0.2},
        "assumptions": ["Outages start independently per source (memoryless) with exponential durations."],
    },
    "duplicates_and_ordering": {
        "title": "Duplicate and out-of-order inputs",
        "simulator_id": "duplicate_out_of_order",
        "category": "correlation_inputs",
        "question": "How many spurious coincident pairs do duplicates create, and how much does cleaning recover?",
        "params": {"n_points": 300, "duplicate_rate": 0.1, "out_of_order_rate": 0.1, "mean_delay_seconds": 30.0},
        "assumptions": ["Duplicates are exact copies arriving shortly after the original."],
    },
}


def list_templates() -> list[dict]:
    out = []
    for tid, t in TEMPLATES.items():
        clean, _ = S.validate(t["simulator_id"], t["params"])
        out.append({"id": tid, **{k: t[k] for k in ("title", "simulator_id", "category", "question", "assumptions")},
                    "simulator_version": S.get(t["simulator_id"]).version, "params": clean})
    return out


def get_template(tid) -> dict | None:
    return next((t for t in list_templates() if t["id"] == tid), None) if isinstance(tid, str) else None
