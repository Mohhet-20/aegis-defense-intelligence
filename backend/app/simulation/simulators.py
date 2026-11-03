"""Registered simulators. Only the entries in REGISTRY can ever run; a request
names a simulator id, which is looked up here -- it is never imported, eval'd
or otherwise resolved dynamically.

Each simulator declares: a parameter schema, documented metrics with units,
which statements are assumptions, and its limitations. `run()` returns metrics
(None where undefined), a bounded preview, and notes."""
from __future__ import annotations

import bisect
import math
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import generator as gen
from .errors import ResourceLimitError, SimulationError
from .params import ParamSpec, validate_params

P = ParamSpec
G = gen.GENERATOR_SPECS


def _g(*names, **overrides) -> list[ParamSpec]:
    out = []
    for n in names:
        s = G[n]
        if n in overrides:
            s = ParamSpec(s.name, s.type, s.description, overrides[n], s.unit, s.min, s.max, s.choices)
        out.append(s)
    return out


@dataclass(frozen=True)
class MetricDoc:
    name: str
    unit: str
    description: str
    higher_is: str = "neutral"  # better | worse | neutral -- only a reading aid


@dataclass
class SimResult:
    metrics: dict
    preview: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    dataset_header: Optional[dict] = None


@dataclass(frozen=True)
class Simulator:
    id: str
    version: str
    title: str
    description: str
    specs: dict
    metrics: tuple
    assumptions: tuple
    limitations: tuple
    run: Callable[[dict, int, Optional[float]], SimResult]

    def doc(self) -> dict:
        return {"id": self.id, "version": self.version, "title": self.title, "description": self.description,
                "parameters": [s.doc() for s in self.specs.values()],
                "metrics": [m.__dict__ for m in self.metrics], "assumptions": list(self.assumptions),
                "limitations": list(self.limitations)}


def _check_deadline(deadline: Optional[float]) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise ResourceLimitError("simulation exceeded its time budget")


def _ratio(a: float, b: float) -> Optional[float]:
    return a / b if b else None


# ---------------------------------------------------------------- 1. threshold detection

def _rolling_median_mad(vals: list[float], window: int, deadline) -> list[tuple[float, float]]:
    out, half = [], window // 2
    n = len(vals)
    for i in range(n):
        if i % 500 == 0:
            _check_deadline(deadline)
        seg = vals[max(0, i - half): min(n, i + half + 1)]
        med = statistics.median(seg)
        mad = statistics.median([abs(v - med) for v in seg])
        out.append((med, mad))
    return out


def _run_threshold(params: dict, seed: int, deadline: Optional[float]) -> SimResult:
    ds = gen.generate({k: v for k, v in params.items() if k in G}, seed, deadline=deadline)
    recs = [r for r in ds["records"] if r["source_id"] == "synthetic-source-0"]
    if params["deduplicate"]:
        seen, uniq = set(), []
        for r in recs:
            if r["seq"] not in seen:
                seen.add(r["seq"])
                uniq.append(r)
        recs = uniq
    recs.sort(key=lambda r: (r["event_time_s"], r["record_id"]))
    vals = [r["value"] for r in recs]
    stats = _rolling_median_mad(vals, params["window"], deadline) if vals else []
    tp = fp = fn = tn = 0
    flagged_idx = []
    k, floor = params["threshold_k"], params["min_scale"]
    for i, (r, (med, mad)) in enumerate(zip(recs, stats)):
        scale = max(1.4826 * mad, floor)
        flag = abs(r["value"] - med) > k * scale
        truth = r["is_outlier"]
        tp += flag and truth
        fp += flag and not truth
        fn += (not flag) and truth
        tn += (not flag) and not truth
        if flag:
            flagged_idx.append(i)
    n = len(recs)
    prec, rec = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    f1 = None if prec is None or rec is None or (prec + rec) == 0 else 2 * prec * rec / (prec + rec)
    metrics = {"records_evaluated": n, "records_missing": ds["header"]["n_dropped_missing"], "anomalies_injected": tp + fn,
               "true_positives": tp, "false_positives": fp, "false_negatives": fn, "true_negatives": tn,
               "precision": prec, "recall": rec, "f1": f1, "flagged_fraction": _ratio(tp + fp, n)}
    flagged_set = set(flagged_idx)
    preview = [{"event_time_s": r["event_time_s"], "value": r["value"], "is_injected_anomaly": r["is_outlier"], "flagged": i in flagged_set}
               for i, r in enumerate(recs[:200])]
    notes = ["Scale = max(1.4826 x rolling MAD, min_scale); a record is flagged when |value - rolling median| > threshold_k x scale."]
    if metrics["anomalies_injected"] == 0:
        notes.append("No anomalies were injected at this outlier_rate/seed, so recall is undefined.")
    return SimResult(metrics, preview, notes, ds["header"])


THRESHOLD = Simulator(
    id="threshold_detection", version="1.0.0", title="Threshold anomaly detection under data-quality assumptions",
    description="Generates a synthetic series with injected spikes, noise and gaps, applies a rolling-median/MAD threshold detector, "
                "and scores it against the injected ground truth.",
    specs={s.name: s for s in (
        _g("n_points", "noise_sd", "missing_rate", "outlier_rate", "outlier_magnitude", "duplicate_rate", "baseline", "amplitude", "period_points")
        + [P("threshold_k", "float", "Flag when the deviation exceeds this many robust standard deviations.", 4.0, "x scale", 0.5, 20),
           P("window", "int", "Rolling window length (odd values recommended).", 21, "records", 3, 201),
           P("min_scale", "float", "Floor for the robust scale so flat stretches do not flag everything.", 0.1, "value units", 0.0001, 1000),
           P("deduplicate", "bool", "Drop duplicate deliveries (by sequence number) before detecting.", True)])},
    metrics=(MetricDoc("records_evaluated", "records", "Records the detector saw (source 0)."),
             MetricDoc("records_missing", "records", "Samples never delivered (all sources)."),
             MetricDoc("anomalies_injected", "records", "Ground-truth injected spikes among evaluated records."),
             MetricDoc("true_positives", "records", "Injected spikes that were flagged.", "better"),
             MetricDoc("false_positives", "records", "Normal records that were flagged.", "worse"),
             MetricDoc("false_negatives", "records", "Injected spikes that were missed.", "worse"),
             MetricDoc("true_negatives", "records", "Normal records not flagged."),
             MetricDoc("precision", "fraction", "TP/(TP+FP); undefined if nothing was flagged.", "better"),
             MetricDoc("recall", "fraction", "TP/(TP+FN); undefined if no anomalies were injected.", "better"),
             MetricDoc("f1", "fraction", "Harmonic mean of precision and recall; undefined if either is.", "better"),
             MetricDoc("flagged_fraction", "fraction", "Share of evaluated records flagged.")),
    assumptions=("Anomalies are isolated symmetric spikes of fixed size.", "Noise is Gaussian and independent between samples.",
                 "The underlying signal is a smooth sinusoid, so a rolling median tracks it."),
    limitations=("Scores describe this detector on this synthetic model only; they do not predict performance on real sensor data.",
                 "Real anomalies are rarely isolated fixed-size spikes."),
    run=_run_threshold)


# ---------------------------------------------------------------- 2. source availability / freshness

def _run_availability(params: dict, seed: int, deadline: Optional[float]) -> SimResult:
    n_src, dur = params["n_sources"], params["duration_hours"] * 3600.0
    step = params["update_interval_s"]
    n_upd = int(dur // step)
    if n_src * n_upd > 200_000:
        raise ResourceLimitError("n_sources x updates exceeds the 200000 limit; raise update_interval_s or lower duration_hours")
    rng_f, rng_r, rng_d = (random.Random(f"{seed}:{x}") for x in ("fail", "recover", "delay"))
    p_fail = 1 - math.exp(-params["failure_rate_per_hour"] * step / 3600.0)
    p_rec = 1 - math.exp(-step / 60.0 / params["mean_outage_minutes"])
    arrivals: list[list[tuple[float, float]]] = []  # per source: (arrival, generated)
    delays, outages, expected, received, longest_gap = [], 0, 0, 0, 0.0
    for s in range(n_src):
        up, rows, gap_start = True, [], None
        for j in range(n_upd):
            if j % 2000 == 0:
                _check_deadline(deadline)
            u_f, u_r, u_d = rng_f.random(), rng_r.random(), rng_d.random()
            if up and u_f < p_fail:
                up, outages, gap_start = False, outages + 1, j * step
            elif (not up) and u_r < p_rec:
                up = True
                longest_gap = max(longest_gap, j * step - (gap_start or 0.0))
                gap_start = None
            expected += 1
            if up:
                d = -math.log(1 - u_d) * params["mean_delay_s"] if params["mean_delay_s"] > 0 else 0.0
                rows.append((j * step + d, j * step))
                delays.append(d)
                received += 1
        if gap_start is not None:
            longest_gap = max(longest_gap, n_upd * step - gap_start)
        rows.sort()
        arrivals.append(rows)
    arr_times = [[a for a, _ in rows] for rows in arrivals]
    # prefix max of generation time by arrival order -> newest data available at time t
    newest = []
    for rows in arrivals:
        m, acc = -1.0, []
        for _, g in rows:
            m = max(m, g)
            acc.append(m)
        newest.append(acc)
    samples = int(dur // 60)
    fresh_any = fresh_frac_sum = 0.0
    ages = []
    for t_i in range(1, samples + 1):
        if t_i % 2000 == 0:
            _check_deadline(deadline)
        t = t_i * 60.0
        fresh_n = 0
        for s in range(n_src):
            idx = bisect.bisect_right(arr_times[s], t) - 1
            if idx >= 0:
                age = t - newest[s][idx]
                ages.append(age)
                if age <= params["freshness_threshold_s"]:
                    fresh_n += 1
        fresh_frac_sum += fresh_n / n_src
        fresh_any += 1 if fresh_n > 0 else 0
    ages.sort()
    metrics = {"updates_expected": expected, "updates_received": received, "received_fraction": _ratio(received, expected),
               "outage_count": outages, "longest_outage_s": longest_gap if outages else 0.0,
               "mean_delay_s": (sum(delays) / len(delays)) if delays else None,
               "mean_age_s": (sum(ages) / len(ages)) if ages else None,
               "p95_age_s": ages[min(len(ages) - 1, int(0.95 * len(ages)))] if ages else None,
               "mean_fraction_sources_fresh": _ratio(fresh_frac_sum, samples),
               "fraction_time_any_source_fresh": _ratio(fresh_any, samples)}
    return SimResult(metrics, [], ["Freshness is sampled once per simulated minute. Age = time since the newest delivered update was generated."])


AVAIL = Simulator(
    id="source_availability", version="1.0.0", title="Source availability and data freshness",
    description="Simulates several sources that each emit periodic updates, fail and recover (two-state Markov outages) and deliver with delay; "
                "reports delivery and data-age statistics against a freshness requirement.",
    specs={s.name: s for s in [
        P("n_sources", "int", "Simulated sources.", 3, "sources", 1, 10),
        P("duration_hours", "float", "Simulated duration.", 24.0, "h", 0.1, 168),
        P("update_interval_s", "float", "Seconds between expected updates.", 60.0, "s", 10, 3600),
        P("failure_rate_per_hour", "float", "Mean outage starts per source-hour while up.", 0.2, "1/h", 0, 60),
        P("mean_outage_minutes", "float", "Mean outage duration.", 15.0, "min", 0.5, 1440),
        P("mean_delay_s", "float", "Mean exponential delivery delay.", 5.0, "s", 0, 3600),
        P("freshness_threshold_s", "float", "A source is 'fresh' when its newest data is at most this old.", 180.0, "s", 1, 86400)]},
    metrics=(MetricDoc("updates_expected", "updates", "Updates scheduled across sources."),
             MetricDoc("updates_received", "updates", "Updates delivered.", "better"),
             MetricDoc("received_fraction", "fraction", "Received / expected.", "better"),
             MetricDoc("outage_count", "outages", "Outages started across sources.", "worse"),
             MetricDoc("longest_outage_s", "s", "Longest single outage.", "worse"),
             MetricDoc("mean_delay_s", "s", "Mean delivery delay of received updates.", "worse"),
             MetricDoc("mean_age_s", "s", "Mean age of the newest data per source, sampled each minute.", "worse"),
             MetricDoc("p95_age_s", "s", "95th percentile of that age (empirical).", "worse"),
             MetricDoc("mean_fraction_sources_fresh", "fraction", "Average share of sources meeting the freshness threshold.", "better"),
             MetricDoc("fraction_time_any_source_fresh", "fraction", "Share of minutes with at least one fresh source.", "better")),
    assumptions=("Outages are memoryless (exponential up/down durations) and independent between sources.", "Delivery delay is exponential and independent of outages.",
                 "Sources are identical in their failure behaviour."),
    limitations=("Real outages are correlated (shared networks, power, weather); independence here usually understates simultaneous loss.",
                 "Results describe this model, not any actual deployment."),
    run=_run_availability)


# ---------------------------------------------------------------- 3. duplicates / ordering / correlation

def _run_ordering(params: dict, seed: int, deadline: Optional[float]) -> SimResult:
    ds = gen.generate({k: v for k, v in params.items() if k in G}, seed, deadline=deadline)
    recs = ds["records"]  # arrival order
    truth_n = ds["header"]["record_count"] - ds["header"]["n_duplicates"]
    window = params["reorder_buffer_s"]
    cw = params["correlation_window_s"]

    def inversions(order: list[dict]) -> int:
        bad, mx = 0, {}
        for r in order:
            s = r["source_id"]
            if r["event_time_s"] < mx.get(s, -math.inf):
                bad += 1
            mx[s] = max(mx.get(s, -math.inf), r["event_time_s"])
        return bad

    def pairs(times: list[float]) -> int:
        ts, total, j = sorted(times), 0, 0
        for i, t in enumerate(ts):
            while ts[j] < t - cw:
                j += 1
            total += i - j
        return total

    naive_inv = inversions(recs)
    # bounded reorder buffer: a record whose arrival is more than `window` after its event time is "late" and bypasses ordering
    on_time = [r for r in recs if r["arrival_time_s"] - r["event_time_s"] <= window + (0 if r["source_id"] != f"synthetic-source-{params['n_sources'] - 1}" else abs(params["timestamp_skew_seconds"]))]
    late = len(recs) - len(on_time)
    seen, cleaned = set(), []
    for r in sorted(on_time, key=lambda r: (r["event_time_s"], r["arrival_time_s"], r["record_id"])):
        key = (r["source_id"], r["seq"])
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(r)
    dup_removed = len(on_time) - len(cleaned)
    naive_pairs = pairs([r["event_time_s"] for r in recs])
    clean_pairs = pairs([r["event_time_s"] for r in cleaned])
    # spurious pairs: pairs that exist only because a record was delivered twice
    all_unique_pairs = pairs([r["event_time_s"] for r in recs if not r["is_duplicate"]])
    metrics = {"records_received": len(recs), "unique_events_delivered": truth_n, "duplicates_delivered": ds["header"]["n_duplicates"],
               "out_of_order_records_naive": naive_inv, "out_of_order_fraction_naive": _ratio(naive_inv, len(recs)),
               "late_beyond_buffer": late, "duplicates_removed": dup_removed, "records_after_cleaning": len(cleaned),
               "naive_event_count_error": len(recs) - truth_n, "naive_correlated_pairs": naive_pairs,
               "cleaned_correlated_pairs": clean_pairs, "spurious_pairs_from_duplicates": naive_pairs - all_unique_pairs,
               "events_lost_to_late_arrival": truth_n - len({(r["source_id"], r["seq"]) for r in cleaned})}
    return SimResult(metrics, [], ["'Correlated pair' = two records of any source whose reported event times are within correlation_window_s. "
                                   "This is a counting model of coincidence, not of the platform's correlation algorithm."],
                     ds["header"])


ORDERING = Simulator(
    id="duplicate_out_of_order", version="1.0.0", title="Duplicate and out-of-order input effects",
    description="Compares naive arrival-order processing with duplicate removal plus a bounded reorder buffer, "
                "reporting record counts, ordering violations and spurious coincident-event pairs.",
    specs={s.name: s for s in (
        _g("n_points", "n_sources", "duplicate_rate", "out_of_order_rate", "mean_delay_seconds", "timestamp_skew_seconds", "missing_rate", "interval_seconds")
        + [P("reorder_buffer_s", "float", "Records arriving later than this after their event time bypass the reorder buffer and are dropped.", 300.0, "s", 0, 86400),
           P("correlation_window_s", "float", "Two records within this event-time gap count as a coincident pair.", 60.0, "s", 1, 3600)])},
    metrics=(MetricDoc("records_received", "records", "Records delivered (including duplicates)."),
             MetricDoc("unique_events_delivered", "records", "Distinct (source, sequence) records delivered."),
             MetricDoc("duplicates_delivered", "records", "Duplicate deliveries injected."),
             MetricDoc("out_of_order_records_naive", "records", "Records whose event time is earlier than an already-seen record of the same source."),
             MetricDoc("out_of_order_fraction_naive", "fraction", "That count / records received."),
             MetricDoc("late_beyond_buffer", "records", "Records dropped by the bounded buffer as too late.", "worse"),
             MetricDoc("duplicates_removed", "records", "Duplicates removed by cleaning.", "better"),
             MetricDoc("records_after_cleaning", "records", "Records remaining after cleaning."),
             MetricDoc("naive_event_count_error", "records", "Received minus unique delivered (overcount from duplicates).", "worse"),
             MetricDoc("naive_correlated_pairs", "pairs", "Coincident pairs counted on raw arrivals."),
             MetricDoc("cleaned_correlated_pairs", "pairs", "Coincident pairs after cleaning."),
             MetricDoc("spurious_pairs_from_duplicates", "pairs", "Pairs created only by duplicate deliveries.", "worse"),
             MetricDoc("events_lost_to_late_arrival", "records", "Unique events lost because they arrived beyond the buffer.", "worse")),
    assumptions=("Duplicates are exact copies delivered up to 30 s later.", "Skewed timestamps affect only the last source and are not corrected by cleaning.",
                 "Lateness is judged by arrival minus reported event time."),
    limitations=("Counts coincident pairs only; it does not run the platform's correlation rules.", "Synthetic data; see generator limitations."),
    run=_run_ordering)


REGISTRY: dict[str, Simulator] = {s.id: s for s in (THRESHOLD, AVAIL, ORDERING)}


def get(simulator_id: str) -> Simulator:
    sim = REGISTRY.get(simulator_id) if isinstance(simulator_id, str) else None
    if sim is None:
        raise SimulationError(f"unknown simulator '{str(simulator_id)[:60]}'", "unknown_simulator")
    return sim


def validate(simulator_id: str, params) -> tuple[dict, list[dict]]:
    sim = get(simulator_id)
    clean, errs = validate_params(sim.specs, params)
    if not errs:
        try:
            if "n_points" in clean:
                gen.check_limits(dict(gen.validate_params(gen.GENERATOR_SPECS, {k: v for k, v in clean.items() if k in G})[0]))
        except ResourceLimitError as exc:
            errs.append({"param": "n_points", "message": str(exc)})
    return clean, errs


def execute(simulator_id: str, params: dict, seed: int, *, max_seconds: float) -> SimResult:
    sim = get(simulator_id)
    clean, errs = validate(simulator_id, params)
    if errs:
        raise SimulationError("invalid parameters: " + "; ".join(f"{e['param']}: {e['message']}" for e in errs[:5]), "invalid_parameters")
    deadline = time.monotonic() + max_seconds
    try:
        res = sim.run(clean, seed, deadline)
    except (SimulationError, ResourceLimitError):
        raise
    except (ZeroDivisionError, ValueError, OverflowError) as exc:
        raise SimulationError(f"numerical error during simulation ({type(exc).__name__})", "numerical_error")
    for k, v in res.metrics.items():
        if isinstance(v, float) and not math.isfinite(v):
            res.metrics[k] = None
        elif isinstance(v, float):
            res.metrics[k] = round(v, 8)
    return res
