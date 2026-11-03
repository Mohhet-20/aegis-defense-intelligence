"""What-if comparison and sensitivity analysis over registered simulators.

Interpretation rules baked in here (and repeated in every response):
* A comparison shows how two SIMULATED runs differ. It is an association
  within the experiment, never a real-world causal effect.
* If more than one input differs (including the seed) no single input is
  credited with the change.
* Spread across seeds is variability of the simulated outcome. No confidence
  interval is computed; percentiles are labelled empirical.
"""
from __future__ import annotations

import time

from . import simulators as S
from .errors import ResourceLimitError, SimulationError
from .stats import relative_diff, summarize

MAX_SWEEP_PARAMS = 4
MAX_VALUES = 9
MAX_REPS = 20
MAX_TOTAL_RUNS = 200

GENERAL_CAVEATS = [
    "Both runs are simulations on synthetic data. Differences show an association within this experiment, not a real-world causal effect.",
    "Metrics are only compared when both runs report them; absolute and relative differences are shown where mathematically defined.",
]


def _metric_unit(sim: S.Simulator, name: str) -> str:
    return next((m.unit for m in sim.metrics if m.name == name), "")


def compare_runs(base: dict, alts: list[dict]) -> dict:
    """Each run: {run_id, label, config_snapshot, metrics}. Pure function."""
    if not alts or len(alts) > 3:
        raise SimulationError("provide between 1 and 3 alternative runs", "invalid_comparison")
    bc = base["config_snapshot"]
    out = []
    for alt in alts:
        ac = alt["config_snapshot"]
        item: dict = {"run_id": alt["run_id"], "label": alt.get("label"), "warnings": [], "metrics": []}
        if ac["simulator_id"] != bc["simulator_id"]:
            item["warnings"].append("Different simulators: metrics are incomparable.")
            item.update(parameter_changes=[], held_constant=[], seed_changed=ac["seed"] != bc["seed"], comparable=False,
                        attribution={"status": "incomparable", "statement": "The runs use different simulators; no metric comparison is made."})
            out.append(item)
            continue
        if ac["simulator_version"] != bc["simulator_version"]:
            item["warnings"].append(f"Simulator versions differ ({bc['simulator_version']} vs {ac['simulator_version']}); algorithm changes may contribute to differences.")
        sim = S.get(bc["simulator_id"])
        changes, held = [], []
        for k in sorted(set(bc["params"]) | set(ac["params"])):
            b, a = bc["params"].get(k), ac["params"].get(k)
            (held if b == a else changes).append({"param": k, "value": b} if b == a else {"param": k, "baseline": b, "alternative": a})
        seed_changed = bc["seed"] != ac["seed"]
        n_diff = len(changes) + (1 if seed_changed else 0) + (1 if ac["simulator_version"] != bc["simulator_version"] else 0)
        if n_diff == 0:
            attr = {"status": "identical_inputs", "statement": "Inputs are identical; any metric difference would indicate non-determinism (none expected)."}
        elif n_diff == 1 and changes:
            attr = {"status": "single_parameter", "statement": f"Only '{changes[0]['param']}' differs and both runs share the seed (and therefore the same underlying random draws). "
                    "The metric changes are associated with that parameter under this model; they do not show a real-world effect."}
        else:
            names = [c["param"] for c in changes] + (["seed"] if seed_changed else []) + (["simulator_version"] if ac["simulator_version"] != bc["simulator_version"] else [])
            attr = {"status": "multiple_inputs", "statement": f"{n_diff} inputs differ ({', '.join(names)}). The change in outputs cannot be attributed to any single input."}
        bm, am = base["metrics"], alt["metrics"]
        for name in sorted(set(bm) | set(am)):
            row = {"name": name, "unit": _metric_unit(sim, name), "baseline": bm.get(name), "alternative": am.get(name),
                   "absolute_diff": None, "relative_diff": None, "comparable": True, "reason": None}
            b, a = bm.get(name), am.get(name)
            if name not in bm or name not in am:
                row.update(comparable=False, reason="metric reported by only one run")
            elif b is None or a is None:
                row.update(comparable=False, reason="metric undefined in at least one run")
            else:
                row["absolute_diff"] = round(a - b, 8)
                row["relative_diff"], row["reason"] = relative_diff(b, a)
            item["metrics"].append(row)
        item.update(parameter_changes=changes, held_constant=held, seed_changed=seed_changed, comparable=True, attribution=attr)
        out.append(item)
    return {"baseline": {"run_id": base["run_id"], "label": base.get("label"), "simulator_id": bc["simulator_id"], "simulator_version": bc["simulator_version"],
                         "params": bc["params"], "seed": bc["seed"]},
            "alternatives": out, "assumptions": list(bc.get("assumptions", [])), "limitations": list(bc.get("limitations", [])),
            "caveats": GENERAL_CAVEATS, "synthetic": True}


# ------------------------------------------------------------------ sensitivity

def _values_for(spec, entry: dict) -> list:
    vals = entry.get("values")
    if vals is not None:
        if not isinstance(vals, list) or not (2 <= len(vals) <= MAX_VALUES):
            raise SimulationError(f"'{spec.name}': provide 2-{MAX_VALUES} values", "invalid_sweep")
        out = list(vals)
    else:
        lo, hi, steps = entry.get("min"), entry.get("max"), entry.get("steps")
        if spec.type not in ("int", "float") or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (lo, hi, steps)):
            raise SimulationError(f"'{spec.name}': min, max and steps (numbers) are required for a range sweep", "invalid_sweep")
        if not (2 <= steps <= MAX_VALUES) or int(steps) != steps or hi <= lo:
            raise SimulationError(f"'{spec.name}': need max > min and 2-{MAX_VALUES} integer steps", "invalid_sweep")
        steps = int(steps)
        out = [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]
        if spec.type == "int":
            out = sorted({int(round(v)) for v in out})
    return out


def plan_sensitivity(simulator_id: str, base_params: dict, sweep: list, reps: int, metric: str) -> dict:
    sim = S.get(simulator_id)
    if not isinstance(sweep, list) or not (1 <= len(sweep) <= MAX_SWEEP_PARAMS):
        raise SimulationError(f"sweep must list 1-{MAX_SWEEP_PARAMS} parameters", "invalid_sweep")
    if not isinstance(reps, int) or isinstance(reps, bool) or not (1 <= reps <= MAX_REPS):
        raise SimulationError(f"repetitions must be between 1 and {MAX_REPS}", "invalid_sweep")
    if metric not in {m.name for m in sim.metrics}:
        raise SimulationError(f"unknown metric '{str(metric)[:40]}' for this simulator", "invalid_sweep")
    plan, seen, total = [], set(), reps
    for entry in sweep:
        if not isinstance(entry, dict) or entry.get("param") not in sim.specs:
            raise SimulationError("each sweep entry needs a valid 'param' for this simulator", "invalid_sweep")
        name = entry["param"]
        if name in seen:
            raise SimulationError(f"parameter '{name}' appears twice", "invalid_sweep")
        seen.add(name)
        spec = sim.specs[name]
        vals = _values_for(spec, entry)
        checked = []
        for v in vals:
            clean, errs = S.validate(simulator_id, dict(base_params, **{name: v}))
            if errs:
                raise SimulationError(f"'{name}': value {v!r} is invalid: {errs[0]['message']}", "invalid_sweep")
            checked.append(clean[name])
        checked = list(dict.fromkeys(checked))
        if len(checked) < 2:
            raise SimulationError(f"'{name}': needs at least 2 distinct values", "invalid_sweep")
        plan.append({"param": name, "values": checked})
        total += len(checked) * reps
    if total > MAX_TOTAL_RUNS:
        raise SimulationError(f"this sweep needs {total} simulation runs; the limit is {MAX_TOTAL_RUNS}", "resource_limit")
    return {"sweep": plan, "repetitions": reps, "metric": metric, "total_runs": total}


def run_sensitivity(simulator_id: str, base_params: dict, base_seed: int, sweep: list, reps: int, metric: str, *, max_seconds: float) -> dict:
    plan = plan_sensitivity(simulator_id, base_params, sweep, reps, metric)
    sim = S.get(simulator_id)
    clean_base, _ = S.validate(simulator_id, base_params)
    end = time.monotonic() + max_seconds
    seeds = [base_seed + i for i in range(reps)]
    executed = 0

    def one(params: dict, seed: int) -> dict:
        nonlocal executed
        left = end - time.monotonic()
        if left <= 0:
            raise ResourceLimitError("sensitivity analysis exceeded its time budget")
        executed += 1
        return S.execute(simulator_id, params, seed, max_seconds=left).metrics

    base_runs = [one(clean_base, s) for s in seeds]
    base_summary = summarize([m.get(metric) for m in base_runs])
    results = []
    for entry in plan["sweep"]:
        points = []
        for v in entry["values"]:
            runs = [one(dict(clean_base, **{entry["param"]: v}), s) for s in seeds]
            all_means = {}
            for name in runs[0]:
                sm = summarize([r.get(name) for r in runs])
                all_means[name] = sm["mean"]
            points.append({"value": v, "metric_summary": summarize([r.get(metric) for r in runs]), "metric_means": all_means})
        means = [p["metric_summary"]["mean"] for p in points if p["metric_summary"]["mean"] is not None]
        effect = (max(means) - min(means)) if len(means) >= 2 else None
        sd = base_summary["sd"]
        results.append({"param": entry["param"], "unit": sim.specs[entry["param"]].unit, "points": points, "effect_range": effect,
                        "exceeds_baseline_seed_variability": (effect > 2 * sd) if (effect is not None and sd is not None) else None})
    ranked = sorted([r for r in results if r["effect_range"] is not None], key=lambda r: (-r["effect_range"], r["param"]))
    return {
        "method": "one_parameter_at_a_time", "metric": metric, "metric_unit": _metric_unit(sim, metric), "repetitions": reps,
        "seeds": seeds, "total_runs": executed, "limits": {"max_params": MAX_SWEEP_PARAMS, "max_values": MAX_VALUES, "max_reps": MAX_REPS, "max_total_runs": MAX_TOTAL_RUNS},
        "baseline_params": clean_base, "baseline_summary": base_summary, "parameters": results,
        "ranking": [{"param": r["param"], "effect_range": r["effect_range"], "exceeds_baseline_seed_variability": r["exceeds_baseline_seed_variability"]} for r in ranked],
        "interpretation": [
            "Each parameter is varied alone while all others stay at their baseline values; interactions between parameters are NOT explored.",
            "All values of a parameter reuse the same seeds (common random numbers), so differences between values mainly reflect the parameter, not different random draws.",
            "'Effect range' is the largest minus smallest mean of the chosen metric across the tested values, in the metric's own units. It describes this simulation over the tested range only.",
            "Spread across seeds (sd, empirical percentiles when n>=5) is variability of the simulated outcome. It is not uncertainty about the real world and no confidence interval is computed.",
            "'exceeds_baseline_seed_variability' is a rough heuristic (effect range > 2 x the baseline's across-seed sd), not a statistical test."],
        "assumptions": list(sim.assumptions), "limitations": list(sim.limitations), "synthetic": True,
    }
