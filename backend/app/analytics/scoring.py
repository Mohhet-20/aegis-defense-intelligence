"""Transparent, advisory review-priority scoring for assessments.

WHAT THIS SCORE IS: a documented additive rule that ranks how much
HUMAN REVIEW ATTENTION an assessment deserves, based only on the
structure of what the analyst already recorded -- how much evidence
contradicts it, how many cited events are in unresolved conflict, how
many information gaps were stated, whether there is any supporting
evidence at all, and the analyst's own stated confidence.

WHAT IT IS NOT: a threat score, a probability, a prediction of intent,
or a model output. Its inputs are a closed list (below); nothing about
identity, appearance, protected characteristics, or a lone statistical
anomaly is, or can be, an input. It never triggers an action.

Model confidence, evidence quality, source reliability and uncertainty
are reported by the service as SEPARATE fields beside the score and are
deliberately not blended into it (see assessment_scoring_service).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

SCORE_SCALE = "0-100 review-priority points (advisory, uncalibrated; not a probability and not a threat level)"
ADVISORY_NOTICE = (
    "Advisory only. This number ranks which assessments most need human review; it is not a finding about any "
    "person or event, and it never triggers an action by itself."
)

# Closed list of the only inputs a rule may use.
ALLOWED_INPUTS = (
    "contradicting_evidence_count", "unresolved_conflict_count", "information_gap_count",
    "supporting_evidence_count", "analyst_confidence_level",
)

BANDS = (("high", 50.0), ("medium", 25.0), ("low", 0.0))  # score >= threshold -> band

RULES: dict[str, dict[str, Any]] = {
    "review_priority_v1": {
        "version": "1",
        "description": "Additive review-priority points from contradiction, conflict, information gaps, missing support and stated analyst confidence.",
        "config": {
            "contradicting_points_each": 10.0, "contradicting_cap": 30.0,
            "conflict_points_each": 12.0, "conflict_cap": 36.0,
            "gap_points_each": 4.0, "gap_cap": 16.0,
            "no_supporting_evidence_points": 15.0,
            "confidence_points": {"low": 10.0, "moderate": 4.0, "high": 0.0, "unstated": 6.0},
        },
    },
}
MAX_OVERRIDE_VALUE = 50.0


class ScoringConfigError(ValueError):
    pass


@dataclass
class ScoringInputs:
    contradicting_evidence_count: int
    unresolved_conflict_count: int
    information_gap_count: int
    supporting_evidence_count: int
    analyst_confidence_level: Optional[str]


def resolve_config(rule_key: str, overrides: Optional[dict]) -> dict:
    if rule_key not in RULES:
        raise ScoringConfigError(f"unknown scoring rule '{rule_key}' (available: {sorted(RULES)})")
    config = {k: (dict(v) if isinstance(v, dict) else v) for k, v in RULES[rule_key]["config"].items()}
    for key, value in (overrides or {}).items():
        if key not in config:
            raise ScoringConfigError(f"unknown config key '{key}' for rule '{rule_key}' (allowed: {sorted(config)})")
        if key == "confidence_points":
            if not isinstance(value, dict) or set(value) - set(config[key]):
                raise ScoringConfigError(f"confidence_points keys must be within {sorted(config[key])}")
            for k, v in value.items():
                _check_points(f"confidence_points.{k}", v)
            config[key].update({k: float(v) for k, v in value.items()})
        else:
            _check_points(key, value)
            config[key] = float(value)
    return config


def _check_points(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not (0.0 <= float(value) <= MAX_OVERRIDE_VALUE):
        raise ScoringConfigError(f"{name} must be a number between 0 and {MAX_OVERRIDE_VALUE}")


def band_for(score: float) -> str:
    for name, threshold in BANDS:
        if score >= threshold:
            return name
    return "low"


def score_assessment(rule_key: str, inputs: ScoringInputs, config: dict) -> dict:
    """Returns {"score", "band", "factors"}. Each factor states its raw
    input, the points it contributed, its cap, and why -- so the score
    is exactly the sum of what is shown (before the 100-point ceiling)."""
    factors = []

    def add(key: str, label: str, raw: Any, points: float, cap: float, rationale: str) -> None:
        factors.append({"key": key, "label": label, "input_value": raw, "points": round(points, 2), "max_points": cap, "rationale": rationale})

    c = inputs.contradicting_evidence_count
    pts = min(c * config["contradicting_points_each"], config["contradicting_cap"])
    add("contradicting_evidence", "Evidence recorded as contradicting", c, pts, config["contradicting_cap"],
        f"{config['contradicting_points_each']:g} points per contradicting item, capped at {config['contradicting_cap']:g}.")

    k = inputs.unresolved_conflict_count
    pts = min(k * config["conflict_points_each"], config["conflict_cap"])
    add("unresolved_conflicts", "Unresolved conflicts between cited events", k, pts, config["conflict_cap"],
        f"{config['conflict_points_each']:g} points per unresolved conflict among cited events, capped at {config['conflict_cap']:g}.")

    g = inputs.information_gap_count
    pts = min(g * config["gap_points_each"], config["gap_cap"])
    add("information_gaps", "Information gaps stated by the analyst", g, pts, config["gap_cap"],
        f"{config['gap_points_each']:g} points per stated gap, capped at {config['gap_cap']:g}.")

    s = inputs.supporting_evidence_count
    pts = config["no_supporting_evidence_points"] if s == 0 else 0.0
    add("no_supporting_evidence", "No supporting evidence linked", s, pts, config["no_supporting_evidence_points"],
        "Applies only when zero supporting items are linked.")

    level = inputs.analyst_confidence_level or "unstated"
    pts = config["confidence_points"].get(level, config["confidence_points"]["unstated"])
    add("analyst_confidence", "Analyst's stated confidence", level, pts, max(config["confidence_points"].values()),
        "Lower or missing stated confidence raises review priority; this is the analyst's own qualitative level, not a model output.")

    total = min(sum(f["points"] for f in factors), 100.0)
    return {"score": round(total, 2), "band": band_for(total), "factors": factors}
