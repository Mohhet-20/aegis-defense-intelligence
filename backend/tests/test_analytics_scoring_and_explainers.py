"""Pure scoring-rule and explainer tests."""
from __future__ import annotations

import pytest

from app.analytics import explainers, scoring


def _inputs(**kw):
    base = dict(contradicting_evidence_count=0, unresolved_conflict_count=0, information_gap_count=0,
                supporting_evidence_count=3, analyst_confidence_level="high")
    base.update(kw)
    return scoring.ScoringInputs(**base)


def test_score_is_exactly_the_sum_of_the_shown_factor_points():
    cfg = scoring.resolve_config("review_priority_v1", None)
    r = scoring.score_assessment("review_priority_v1", _inputs(contradicting_evidence_count=2, unresolved_conflict_count=1,
                                                                information_gap_count=3, analyst_confidence_level="low"), cfg)
    by_key = {f["key"]: f for f in r["factors"]}
    assert by_key["contradicting_evidence"]["points"] == 20
    assert by_key["unresolved_conflicts"]["points"] == 12
    assert by_key["information_gaps"]["points"] == 12
    assert by_key["no_supporting_evidence"]["points"] == 0
    assert by_key["analyst_confidence"]["points"] == 10
    assert r["score"] == sum(f["points"] for f in r["factors"]) == 54
    assert r["band"] == "high"


def test_caps_ceiling_and_bands():
    cfg = scoring.resolve_config("review_priority_v1", None)
    big = scoring.score_assessment("review_priority_v1", _inputs(contradicting_evidence_count=99, unresolved_conflict_count=99,
                                                                  information_gap_count=99, supporting_evidence_count=0,
                                                                  analyst_confidence_level=None), cfg)
    by_key = {f["key"]: f for f in big["factors"]}
    assert by_key["contradicting_evidence"]["points"] == 30 and by_key["unresolved_conflicts"]["points"] == 36
    assert big["score"] <= 100
    clean = scoring.score_assessment("review_priority_v1", _inputs(), cfg)
    assert clean["score"] == 0 and clean["band"] == "low"
    assert scoring.band_for(25) == "medium" and scoring.band_for(24.99) == "low" and scoring.band_for(50) == "high"


def test_unstated_confidence_scores_differently_from_high():
    cfg = scoring.resolve_config("review_priority_v1", None)
    assert scoring.score_assessment("review_priority_v1", _inputs(analyst_confidence_level=None), cfg)["score"] == 6


def test_overrides_are_validated_and_reproducible():
    cfg = scoring.resolve_config("review_priority_v1", {"gap_points_each": 10, "confidence_points": {"low": 20}})
    assert cfg["gap_points_each"] == 10.0 and cfg["confidence_points"]["low"] == 20.0 and cfg["confidence_points"]["high"] == 0.0
    for bad in ({"nope": 1}, {"gap_points_each": -1}, {"gap_points_each": 999}, {"gap_points_each": "x"},
                {"gap_points_each": True}, {"confidence_points": {"bogus": 1}}):
        with pytest.raises(scoring.ScoringConfigError):
            scoring.resolve_config("review_priority_v1", bad)
    with pytest.raises(scoring.ScoringConfigError):
        scoring.resolve_config("threat_score_v9", None)


def test_defaults_are_not_mutated_by_overrides():
    scoring.resolve_config("review_priority_v1", {"confidence_points": {"low": 33}})
    assert scoring.RULES["review_priority_v1"]["config"]["confidence_points"]["low"] == 10.0


def test_rule_inputs_are_a_closed_list_with_no_identity_or_appearance_inputs():
    assert set(scoring.ALLOWED_INPUTS) == {"contradicting_evidence_count", "unresolved_conflict_count", "information_gap_count",
                                           "supporting_evidence_count", "analyst_confidence_level"}
    assert "advisory" in scoring.ADVISORY_NOTICE.lower() and "never triggers an action" in scoring.ADVISORY_NOTICE


# ------------------------------ explainers ------------------------------
def _risk(**kw):
    out = {"output_type": "risk_assessment", "model": {"name": "m", "version": "1", "evaluation_metadata": {}},
           "features": {"contributing_factors": [{"name": "recent_events", "weight": 0.4}]}, "confidence": None}
    out.update(kw)
    return out


def _det():
    return {"output_type": "detection_result", "confidence": 0.8,
            "model": {"name": "hog", "version": "v1", "adapter_key": "opencv_hog_person_v1", "evaluation_metadata": {}},
            "prediction": {"label": "person"}, "features": {"bbox": {"x_min": 0.1, "y_min": 0.1, "x_max": 0.3, "y_max": 0.5}}}


def test_method_compatibility_matrix():
    risk = {m["method_key"]: m for m in explainers.describe_methods(_risk())}
    assert risk["rule_based_factors"]["supported"] and not risk["detection_confidence_metadata"]["supported"]
    assert not risk["linear_feature_contribution"]["supported"] and not risk["shap"]["supported"]
    det = {m["method_key"]: m for m in explainers.describe_methods(_det())}
    assert det["detection_confidence_metadata"]["supported"] and not det["rule_based_factors"]["supported"]
    assert det["shap"]["limitation"]


def test_rule_based_without_factors_is_unsupported_not_fabricated():
    res = explainers.explain(_risk(features={"contributing_factors": []}), "rule_based_factors")
    assert res["supported"] is False and "no contributing factors" in res["limitation"]


def test_supported_explanation_carries_non_causal_note_and_only_recorded_values():
    res = explainers.explain(_risk(), None)
    assert res["supported"] and res["method_key"] == "rule_based_factors"
    assert [i["name"] for i in res["items"]] == ["recent_events"]
    assert "not causal" in res["interpretation_note"]
    det = explainers.explain(_det(), "detection_confidence_metadata")
    assert {i["name"] for i in det["items"]} >= {"class_label", "reported_confidence", "box_area_fraction"}
    assert "no attribution method was run" in det["method_detail"]


def test_linear_contributions_are_exact_and_sorted():
    out = _risk(features={"feature_values": {"a": 2.0, "b": -3.0}})
    out["model"]["evaluation_metadata"] = {"linear_weights": {"a": 0.5, "b": 1.0}}
    res = explainers.explain(out, "linear_feature_contribution")
    assert res["supported"] and res["items"][0] == {"name": "b", "value": -3.0, "weight": 1.0, "contribution": -3.0}
    assert res["items"][1]["contribution"] == 1.0


def test_linear_missing_feature_values_or_weights_is_unsupported():
    out = _risk(features={"feature_values": {"a": 2.0}})
    out["model"]["evaluation_metadata"] = {"linear_weights": {"a": 0.5, "b": 1.0}}
    assert "missing" in explainers.explain(out, "linear_feature_contribution")["limitation"].lower()
    assert explainers.explain(_risk(), "linear_feature_contribution")["supported"] is False


def test_shap_is_reported_unsupported_with_reason():
    res = explainers.explain(_risk(), "shap")
    assert res["supported"] is False and res["limitation"]


def test_unknown_method_raises_and_no_applicable_method_is_stated():
    with pytest.raises(KeyError):
        explainers.explain(_risk(), "magic")
    res = explainers.explain(_risk(features={"contributing_factors": []}), None)
    assert res["supported"] is False and "No registered explanation method applies" in res["limitation"]
