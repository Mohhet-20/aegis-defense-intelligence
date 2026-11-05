"""Pure simulation engine (no database): parameter validation,
deterministic synthetic generation, simulator correctness, statistics edge
cases, comparison attribution rules and sensitivity bounds."""
from __future__ import annotations

import math

import pytest

from app.simulation import analysis as A
from app.simulation import generator as G
from app.simulation import simulators as S
from app.simulation import templates as T
from app.simulation.errors import ResourceLimitError, SimulationError
from app.simulation.params import ParamSpec, validate_params
from app.simulation.stats import quantile, relative_diff, summarize


def gen(**kw):
    clean, errs = validate_params(G.GENERATOR_SPECS, kw)
    assert not errs, errs
    return clean


# ------------------------------------------------------------ parameter validation

SPECS = {"n": ParamSpec("n", "int", "count", 5, "", 1, 10), "x": ParamSpec("x", "float", "x", 0.5, "", 0.0, 1.0),
         "flag": ParamSpec("flag", "bool", "f", False), "mode": ParamSpec("mode", "choice", "m", "a", choices=("a", "b"))}


def test_defaults_are_filled_and_values_kept():
    clean, errs = validate_params(SPECS, {"n": 3})
    assert errs == [] and clean == {"n": 3, "x": 0.5, "flag": False, "mode": "a"}


@pytest.mark.parametrize("raw,param", [
    ({"n": 0}, "n"), ({"n": 11}, "n"), ({"n": 2.5}, "n"), ({"n": True}, "n"), ({"n": "3"}, "n"),
    ({"x": float("nan")}, "x"), ({"x": float("inf")}, "x"), ({"x": -0.1}, "x"), ({"x": 1.0000001}, "x"),
    ({"flag": 1}, "flag"), ({"mode": "c"}, "mode"), ({"nope": 1}, "nope"),
])
def test_invalid_values_rejected(raw, param):
    _, errs = validate_params(SPECS, raw)
    assert any(e["param"] == param for e in errs)


def test_boundaries_inclusive_and_non_dict_rejected():
    assert validate_params(SPECS, {"n": 1, "x": 0.0})[1] == [] and validate_params(SPECS, {"n": 10, "x": 1.0})[1] == []
    assert validate_params(SPECS, [1, 2])[1] and validate_params(SPECS, "n=3")[1]
    assert validate_params(SPECS, {f"k{i}": 1 for i in range(65)})[1]


def test_required_param_without_default_is_flagged():
    _, errs = validate_params({"r": ParamSpec("r", "int", "required", None, "", 0, 5)}, {})
    assert errs and "required" in errs[0]["message"]


def test_param_docs_have_description_range_and_type():
    for sim in S.REGISTRY.values():
        for d in sim.doc()["parameters"]:
            assert d["description"] and d["type"] in {"int", "float", "bool", "choice"}
            if d["type"] in {"int", "float"}:
                assert d["min"] is not None and d["max"] is not None


# ------------------------------------------------------------------ generator

def test_generation_is_deterministic_for_a_seed_and_differs_across_seeds():
    p = gen(n_points=120, n_sources=2, noise_sd=1.5, missing_rate=0.1, outlier_rate=0.05, duplicate_rate=0.05, out_of_order_rate=0.1)
    a, b, c = G.generate(p, 7), G.generate(p, 7), G.generate(p, 8)
    assert a["records"] == b["records"] and a["header"]["content_sha256"] == b["header"]["content_sha256"]
    assert a["header"]["content_sha256"] != c["header"]["content_sha256"]


def test_header_records_provenance_and_every_record_is_labelled_synthetic():
    out = G.generate(gen(n_points=50), 3)
    h = out["header"]
    assert h["synthetic"] is True and h["generator"] == G.GENERATOR_ID and h["generator_version"] == G.GENERATOR_VERSION
    assert h["seed"] == 3 and h["params"]["n_points"] == 50 and h["limitations"] and h["record_count"] == len(out["records"])
    assert all(r["synthetic"] is True for r in out["records"])
    assert "generated_at" in G.stamp(dict(h)) and "generated_at" not in h  # timestamp is outside the hash


def test_missing_rate_removes_records_from_the_same_series():
    full = G.generate(gen(n_points=200, missing_rate=0.0, duplicate_rate=0.0), 11)
    lossy = G.generate(gen(n_points=200, missing_rate=0.3, duplicate_rate=0.0), 11)
    assert 0 < len(lossy["records"]) < len(full["records"])
    full_vals = {(r["source_id"], r["seq"]): r["value"] for r in full["records"]}
    assert all(full_vals[(r["source_id"], r["seq"])] == r["value"] for r in lossy["records"])  # nested sets
    assert lossy["header"]["n_dropped_missing"] == len(full["records"]) - len(lossy["records"])


def test_zero_noise_zero_outliers_is_the_pure_signal():
    out = G.generate(gen(n_points=40, noise_sd=0.0, outlier_rate=0.0, amplitude=0.0, drift_per_point=0.0, baseline=7.0,
                         source_bias_spread=0.0, source_noise_spread=0.0), 1)
    assert {round(r["value"], 9) for r in out["records"]} == {7.0}


def test_duplicates_outliers_and_metadata_gaps_are_flagged_and_counted():
    out = G.generate(gen(n_points=300, duplicate_rate=0.1, outlier_rate=0.1, incomplete_metadata_rate=0.2), 5)
    recs = out["records"]
    assert out["header"]["n_duplicates"] == sum(r["is_duplicate"] for r in recs) > 0
    assert out["header"]["n_outliers"] == sum(r["is_outlier"] and not r["is_duplicate"] for r in recs) > 0
    assert any(not r["metadata"] or any(v is None for v in r["metadata"].values()) for r in recs)


def test_out_of_order_arrivals_exist_when_requested_and_not_otherwise():
    def inversions(recs):
        last, n = {}, 0
        for r in recs:  # sorted by arrival
            if r["source_id"] in last and r["event_time_s"] < last[r["source_id"]]:
                n += 1
            last[r["source_id"]] = max(last.get(r["source_id"], -1e18), r["event_time_s"])
        return n
    assert inversions(G.generate(gen(n_points=300, out_of_order_rate=0.0, mean_delay_seconds=0.0, duplicate_rate=0.0), 2)["records"]) == 0
    assert inversions(G.generate(gen(n_points=300, out_of_order_rate=0.3, mean_delay_seconds=60.0), 2)["records"]) > 0


def test_generator_size_and_time_guards():
    with pytest.raises(ResourceLimitError):
        G.check_limits(gen(n_points=5000, n_sources=5))  # 25k records > 20k cap
    with pytest.raises(SimulationError):
        G.generate(gen(n_points=2000, n_sources=5), 1, deadline=0.0)  # deadline already passed
    _, errs = validate_params(G.GENERATOR_SPECS, {"n_points": 10**9})
    assert errs


# ----------------------------------------------------------------- simulators

def test_registry_is_fixed_and_lookup_rejects_unknown_or_non_string_ids():
    assert set(S.REGISTRY) == {"threshold_detection", "source_availability", "duplicate_out_of_order"}
    for bad in ("os.system", "__import__('os')", "", None, 5, "../threshold_detection"):
        with pytest.raises(SimulationError) as e:
            S.get(bad)
        assert e.value.code == "unknown_simulator"


@pytest.mark.parametrize("sid", ["threshold_detection", "source_availability", "duplicate_out_of_order"])
def test_every_simulator_is_reproducible_documented_and_bounded(sid):
    sim = S.REGISTRY[sid]
    a, b = S.execute(sid, {}, 4, max_seconds=20), S.execute(sid, {}, 4, max_seconds=20)
    assert a.metrics == b.metrics and a.preview == b.preview
    assert set(a.metrics) == {m.name for m in sim.metrics}  # documented == returned
    assert all(m.unit for m in sim.metrics) and sim.assumptions and sim.limitations and sim.version
    assert len(a.preview) <= 500
    assert all(v is None or (isinstance(v, (int, float)) and math.isfinite(v)) for v in a.metrics.values())


def test_threshold_confusion_matrix_is_consistent():
    m = S.execute("threshold_detection", {"n_points": 300, "outlier_rate": 0.05, "missing_rate": 0.1}, 9, max_seconds=20).metrics
    assert m["true_positives"] + m["false_negatives"] == m["anomalies_injected"]  # injected spikes that arrived
    total = m["true_positives"] + m["false_positives"] + m["false_negatives"] + m["true_negatives"]
    assert total == m["records_evaluated"] and m["records_missing"] > 0
    if m["precision"] is not None:
        assert m["precision"] == pytest.approx(m["true_positives"] / (m["true_positives"] + m["false_positives"]), abs=1e-6)
    if m["recall"] is not None:
        assert m["recall"] == pytest.approx(m["true_positives"] / (m["true_positives"] + m["false_negatives"]), abs=1e-6)


def test_threshold_undefined_metrics_are_none_not_zero_or_nan():
    m = S.execute("threshold_detection", {"n_points": 200, "outlier_rate": 0.0, "threshold_k": 20.0}, 5, max_seconds=10).metrics
    assert m["anomalies_injected"] == 0 and m["recall"] is None and m["precision"] is None and m["f1"] is None
    m2 = S.execute("threshold_detection", {"n_points": 200, "outlier_rate": 0.05, "threshold_k": 20.0, "outlier_magnitude": 2.0}, 5, max_seconds=10).metrics
    assert m2["true_positives"] == 0 and m2["recall"] == 0.0 and m2["precision"] is None


def test_higher_threshold_flags_no_more_than_lower_threshold():
    lo = S.execute("threshold_detection", {"n_points": 400, "threshold_k": 2.0}, 6, max_seconds=10).metrics["flagged_fraction"]
    hi = S.execute("threshold_detection", {"n_points": 400, "threshold_k": 8.0}, 6, max_seconds=10).metrics["flagged_fraction"]
    assert hi <= lo


def test_availability_without_failures_is_fully_available():
    m = S.execute("source_availability", {"failure_rate_per_hour": 0.0, "mean_delay_s": 1.0, "freshness_threshold_s": 300.0}, 2, max_seconds=10).metrics
    assert m["outage_count"] == 0 and m["longest_outage_s"] == 0 and m["received_fraction"] == pytest.approx(1.0)
    assert m["fraction_time_any_source_fresh"] == pytest.approx(1.0)


def test_availability_degrades_with_more_failures_for_same_seed():
    base = {"duration_hours": 48.0, "mean_outage_minutes": 30.0}
    few = S.execute("source_availability", dict(base, failure_rate_per_hour=0.05), 3, max_seconds=10).metrics
    many = S.execute("source_availability", dict(base, failure_rate_per_hour=2.0), 3, max_seconds=10).metrics
    assert many["received_fraction"] < few["received_fraction"] and many["outage_count"] > few["outage_count"]


def test_ordering_clean_input_has_nothing_to_fix_and_dirty_input_does():
    clean = S.execute("duplicate_out_of_order", {"n_points": 100}, 1, max_seconds=10).metrics
    assert clean["duplicates_delivered"] == 0 and clean["naive_event_count_error"] == 0 and clean["out_of_order_records_naive"] == 0
    dirty = S.execute("duplicate_out_of_order", {"n_points": 200, "duplicate_rate": 0.2, "out_of_order_rate": 0.2, "mean_delay_seconds": 40.0}, 1, max_seconds=10).metrics
    assert dirty["duplicates_delivered"] > 0 and dirty["naive_event_count_error"] == dirty["records_received"] - dirty["unique_events_delivered"] > 0
    assert dirty["records_after_cleaning"] <= dirty["records_received"] and dirty["spurious_pairs_from_duplicates"] >= 0


def test_invalid_simulator_parameters_are_rejected_before_running():
    for sid, bad in [("threshold_detection", {"n_points": -1}), ("threshold_detection", {"unknown": 1}), ("source_availability", {"n_sources": 10**6}),
                     ("duplicate_out_of_order", {"duplicate_rate": 2})]:
        with pytest.raises(SimulationError) as e:
            S.execute(sid, bad, 1, max_seconds=5)
        assert e.value.code == "invalid_parameters"


def test_time_budget_is_enforced():
    with pytest.raises((SimulationError, ResourceLimitError)):
        S.execute("threshold_detection", {"n_points": 5000, "n_sources": 1}, 1, max_seconds=0.0)


def test_templates_reference_registered_simulators_with_valid_params():
    for t in T.list_templates():
        assert t["simulator_id"] in S.REGISTRY and S.validate(t["simulator_id"], t["params"])[1] == []
    assert T.get_template("nope") is None and T.get_template(None) is None


# ----------------------------------------------------------------------- stats

def test_summarize_edge_cases():
    assert summarize([])["mean"] is None and summarize([None, None])["n_undefined"] == 2
    one = summarize([3.0])
    assert one["mean"] == 3.0 and one["sd"] is None and one["sem"] is None and one["p50"] is None
    four = summarize([1, 2, 3, 4])
    assert four["sd"] == pytest.approx(1.2909944) and four["p50"] is None  # <5 values: no quantiles
    five = summarize([1, 2, 3, 4, 5])
    assert five["p50"] == 3 and five["p10"] == pytest.approx(1.4) and five["p90"] == pytest.approx(4.6)
    assert summarize([1, None, float("nan"), 3])["n"] == 2
    assert not any("confidence" in k or k.startswith("ci") for k in five)  # no CI is ever computed


def test_quantile_and_relative_diff():
    assert quantile([1, 2, 3, 4], 0.5) == 2.5 and quantile([7], 0.9) == 7.0
    assert relative_diff(10, 15) == (0.5, None)
    v, why = relative_diff(0, 5)
    assert v is None and "0" in why
    assert relative_diff(None, 5)[0] is None and relative_diff(5, None)[1]


# ------------------------------------------------------------------ comparison

def run_view(rid, sim="threshold_detection", seed=1, **params):
    clean, _ = S.validate(sim, params)
    res = S.execute(sim, clean, seed, max_seconds=10)
    s = S.get(sim)
    return {"run_id": rid, "label": rid, "metrics": res.metrics,
            "config_snapshot": {"simulator_id": sim, "simulator_version": s.version, "params": clean, "seed": seed,
                                "assumptions": list(s.assumptions), "limitations": list(s.limitations)}}


def test_single_parameter_change_is_attributed_to_that_parameter_only_with_caveat():
    res = A.compare_runs(run_view("a", noise_sd=1.0), [run_view("b", noise_sd=3.0)])
    alt = res["alternatives"][0]
    assert alt["attribution"]["status"] == "single_parameter" and [c["param"] for c in alt["parameter_changes"]] == ["noise_sd"]
    assert any(h["param"] == "n_points" for h in alt["held_constant"]) and alt["comparable"] is True
    assert res["synthetic"] is True and any("not a real-world causal" in c or "causal" in c for c in res["caveats"])
    rec = next(m for m in alt["metrics"] if m["name"] == "records_evaluated")
    assert rec["absolute_diff"] == rec["alternative"] - rec["baseline"]


def test_multiple_changes_or_a_seed_change_prevent_single_parameter_attribution():
    res = A.compare_runs(run_view("a"), [run_view("b", noise_sd=3.0, threshold_k=6.0), run_view("c", seed=2, noise_sd=3.0)])
    first, second = res["alternatives"]
    assert first["attribution"]["status"] == "multiple_inputs"
    assert second["seed_changed"] is True and second["attribution"]["status"] == "multiple_inputs"


def test_identical_inputs_and_different_simulators():
    res = A.compare_runs(run_view("a"), [run_view("b")])["alternatives"][0]
    assert res["attribution"]["status"] == "identical_inputs" and all(m["absolute_diff"] in (0, None) for m in res["metrics"])
    other = A.compare_runs(run_view("a"), [run_view("z", sim="source_availability")])["alternatives"][0]
    assert other["comparable"] is False and other["attribution"]["status"] == "incomparable" and other["metrics"] == []


def test_zero_baseline_has_no_relative_difference_and_missing_metric_is_incomparable():
    base = run_view("a", outlier_rate=0.0, threshold_k=20.0)
    alt = run_view("b", outlier_rate=0.0, threshold_k=19.0)
    base["metrics"]["true_positives"] = 0
    alt["metrics"]["true_positives"] = 4
    del alt["metrics"]["f1"]
    ms = {m["name"]: m for m in A.compare_runs(base, [alt])["alternatives"][0]["metrics"]}
    assert ms["true_positives"]["relative_diff"] is None and "0" in ms["true_positives"]["reason"] and ms["true_positives"]["absolute_diff"] == 4
    assert ms["f1"]["comparable"] is False


def test_comparison_alternative_count_is_bounded():
    with pytest.raises(SimulationError):
        A.compare_runs(run_view("a"), [])
    with pytest.raises(SimulationError):
        A.compare_runs(run_view("a"), [run_view(str(i)) for i in range(4)])


# ----------------------------------------------------------------- sensitivity

BASE = {"n_points": 150, "outlier_rate": 0.05}


def test_sensitivity_is_deterministic_bounded_and_ranks_parameters():
    sweep = [{"param": "threshold_k", "values": [2, 4, 8]}, {"param": "noise_sd", "min": 0.5, "max": 2.5, "steps": 3}]
    a = A.run_sensitivity("threshold_detection", BASE, 1, sweep, 3, "f1", max_seconds=60)
    b = A.run_sensitivity("threshold_detection", BASE, 1, sweep, 3, "f1", max_seconds=60)
    assert a == b and a["total_runs"] == 3 + 3 * 3 + 3 * 3 and a["method"] == "one_parameter_at_a_time"
    assert [r["param"] for r in a["ranking"]] and a["synthetic"] is True
    text = " ".join(a["interpretation"]).lower()
    assert "not uncertainty about the real world" in text and "no confidence interval is computed" in text
    assert all("ci_low" not in p["metric_summary"] for r in a["parameters"] for p in r["points"])
    p = a["parameters"][0]["points"][0]["metric_summary"]
    assert p["n"] + p["n_undefined"] == 3 and p["p50"] is None  # 3 reps: no quantiles


def test_sensitivity_quantiles_appear_only_with_enough_repetitions():
    a = A.run_sensitivity("threshold_detection", BASE, 1, [{"param": "threshold_k", "values": [3, 6]}], 5, "flagged_fraction", max_seconds=60)
    assert a["parameters"][0]["points"][0]["metric_summary"]["p50"] is not None


@pytest.mark.parametrize("sweep,reps,metric", [
    ([], 3, "f1"), ([{"param": "noise_sd", "values": [1, 2]}] * 2, 3, "f1"),
    ([{"param": f"p{i}", "values": [1, 2]} for i in range(5)], 3, "f1"),
    ([{"param": "noise_sd", "values": [1, 2]}], 0, "f1"), ([{"param": "noise_sd", "values": [1, 2]}], 21, "f1"),
    ([{"param": "noise_sd", "values": [1, 2]}], 3, "not_a_metric"), ([{"param": "noise_sd", "values": [1]}], 3, "f1"),
    ([{"param": "noise_sd", "values": [1, 1]}], 3, "f1"), ([{"param": "noise_sd", "values": [-5, 2]}], 3, "f1"),
    ([{"param": "noise_sd", "min": 2, "max": 1, "steps": 3}], 3, "f1"), ([{"param": "noise_sd", "min": 0, "max": 1, "steps": 10}], 3, "f1"),
    ([{"param": "os_system", "values": [1, 2]}], 3, "f1"), ([{"param": "noise_sd", "values": list(range(10))}], 3, "f1"),
])
def test_invalid_sweeps_are_rejected(sweep, reps, metric):
    with pytest.raises(SimulationError):
        A.plan_sensitivity("threshold_detection", BASE, sweep, reps, metric)


def test_total_run_cap_and_time_budget():
    sweep = [{"param": "threshold_k", "values": [2, 3, 4, 5, 6, 7, 8, 9, 10]}, {"param": "noise_sd", "min": 0.5, "max": 2, "steps": 9},
             {"param": "outlier_rate", "min": 0.01, "max": 0.1, "steps": 9}]
    with pytest.raises(SimulationError) as e:
        A.plan_sensitivity("threshold_detection", BASE, sweep, 20, "f1")
    assert e.value.code == "resource_limit"
    with pytest.raises(ResourceLimitError):
        A.run_sensitivity("threshold_detection", {"n_points": 2000}, 1, [{"param": "noise_sd", "values": [1, 2]}], 5, "f1", max_seconds=0.0)


def test_sensitivity_detects_a_real_effect_and_zero_effect():
    sa = A.run_sensitivity("source_availability", {}, 1, [{"param": "failure_rate_per_hour", "values": [0.0, 3.0]}], 4, "received_fraction", max_seconds=60)
    pts = sa["parameters"][0]["points"]
    assert pts[0]["metric_summary"]["mean"] > pts[1]["metric_summary"]["mean"] and sa["ranking"][0]["effect_range"] > 0
