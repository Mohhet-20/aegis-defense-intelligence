"""Seeded synthetic time-series generator.

Every output is labelled synthetic (dataset header AND each record). The
generator is a deliberately simple model -- sinusoid + drift + Gaussian noise,
with injected faults -- meant for validating software and data-quality logic,
not for imitating any real sensor.

Reproducibility: each random concern (noise, missingness, delay, outliers,
duplicates, ordering, metadata) has its own seeded stream and a value is drawn
for EVERY slot regardless of the configured rates. Two datasets that share a
seed therefore share their underlying noise, and raising e.g. `missing_rate`
only removes more records from the same underlying series (nested sets). That
makes baseline-vs-alternative comparisons about the changed parameter rather
than about different random draws.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import time
from datetime import datetime, timezone
from typing import Optional

from .errors import ResourceLimitError
from .params import ParamSpec, validate_params

GENERATOR_ID = "aegis.synthetic.timeseries"
GENERATOR_VERSION = "1.0.0"
MAX_RECORDS = 20_000
MAX_STORED_RECORDS = 5_000

P = ParamSpec
GENERATOR_SPECS: dict[str, ParamSpec] = {s.name: s for s in [
    P("n_points", "int", "Samples per source on the true timeline.", 200, "samples", 10, 5000),
    P("n_sources", "int", "Number of simulated sources measuring the same underlying signal.", 1, "sources", 1, 5),
    P("interval_seconds", "float", "True time between samples.", 60.0, "s", 1, 3600),
    P("baseline", "float", "Mean level of the underlying signal.", 20.0, "value units", -1e6, 1e6),
    P("amplitude", "float", "Amplitude of the sinusoidal component.", 5.0, "value units", 0, 1e6),
    P("period_points", "int", "Sinusoid period.", 100, "samples", 4, 5000),
    P("drift_per_point", "float", "Linear drift added per sample.", 0.0, "value units/sample", -10, 10),
    P("noise_sd", "float", "Standard deviation of Gaussian measurement noise for source 0.", 1.0, "value units", 0, 1e5),
    P("source_noise_spread", "float", "Source i has noise_sd*(1+spread*i): lower-reliability later sources.", 0.0, "", 0, 5),
    P("source_bias_spread", "float", "Source i adds a constant bias of spread*i (conflicting sources).", 0.0, "value units", 0, 1e4),
    P("missing_rate", "float", "Probability a sample is never received.", 0.0, "fraction", 0, 0.95),
    P("mean_delay_seconds", "float", "Mean of the exponential delivery delay.", 0.0, "s", 0, 86400),
    P("outlier_rate", "float", "Probability a received sample is an injected spike.", 0.02, "fraction", 0, 0.3),
    P("outlier_magnitude", "float", "Size of an injected spike (sign random).", 10.0, "value units", 0, 1e6),
    P("duplicate_rate", "float", "Probability a sample is delivered twice.", 0.0, "fraction", 0, 0.5),
    P("out_of_order_rate", "float", "Probability a sample is held back so it arrives after later samples.", 0.0, "fraction", 0, 0.5),
    P("timestamp_skew_seconds", "float", "Constant error in the reported timestamps of the last source.", 0.0, "s", -3600, 3600),
    P("incomplete_metadata_rate", "float", "Probability a record is missing its unit/sensor_type metadata.", 0.0, "fraction", 0, 1),
]}

LIMITATIONS = [
    "Synthetic data: produced by a seeded sinusoid + drift + Gaussian-noise model; it does not describe any real sensor, device or environment.",
    "Faults (missing samples, spikes, duplicates, delays, skew, bias) are injected by simple independent random rules; real faults are typically correlated.",
    "Delivery delay follows an exponential distribution; out-of-order arrival is created by an extra random hold-back of up to 10 sampling intervals.",
    "Ground-truth labels (is_outlier, is_duplicate, true_time_s) exist only because the data is simulated.",
]


def generator_docs() -> list[dict]:
    return [s.doc() for s in GENERATOR_SPECS.values()]


def check_limits(p: dict) -> None:
    slots = p["n_points"] * p["n_sources"]
    if slots * (1 + p["duplicate_rate"]) > MAX_RECORDS:
        raise ResourceLimitError(f"n_points x n_sources (+duplicates) may not exceed {MAX_RECORDS} records")


def _r(v: float) -> float:
    return round(float(v), 6)


def canonical_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def generate(params: dict, seed: int, *, deadline: Optional[float] = None) -> dict:
    clean, errs = validate_params(GENERATOR_SPECS, params)
    if errs:
        raise ValueError(errs)
    p = clean
    check_limits(p)
    rng = {k: random.Random(f"{seed}:{k}") for k in ("noise", "missing", "delay", "outlier", "sign", "dup", "dupdelay", "order", "ordershift", "meta")}
    recs: list[dict] = []
    dropped = 0
    n_src = p["n_sources"]
    for s in range(n_src):
        sd = p["noise_sd"] * (1 + p["source_noise_spread"] * s)
        bias = p["source_bias_spread"] * s
        skew = p["timestamp_skew_seconds"] if s == n_src - 1 else 0.0
        for k in range(p["n_points"]):
            if deadline is not None and k % 500 == 0 and time.monotonic() > deadline:
                raise ResourceLimitError("generation exceeded its time budget")
            t = k * p["interval_seconds"]
            truth = p["baseline"] + p["drift_per_point"] * k + p["amplitude"] * math.sin(2 * math.pi * k / p["period_points"])
            g = rng["noise"].gauss(0.0, 1.0)
            u_miss, u_delay = rng["missing"].random(), rng["delay"].random()
            u_out, u_sign = rng["outlier"].random(), rng["sign"].random()
            u_dup, u_dd = rng["dup"].random(), rng["dupdelay"].random()
            u_ord, u_shift, u_meta = rng["order"].random(), rng["ordershift"].random(), rng["meta"].random()
            if u_miss < p["missing_rate"]:
                dropped += 1
                continue
            is_out = u_out < p["outlier_rate"]
            value = truth + bias + sd * g + ((p["outlier_magnitude"] if u_sign < 0.5 else -p["outlier_magnitude"]) if is_out else 0.0)
            delay = -math.log(1.0 - u_delay) * p["mean_delay_seconds"] if p["mean_delay_seconds"] > 0 else 0.0
            if u_ord < p["out_of_order_rate"]:
                delay += (1 + 9 * u_shift) * p["interval_seconds"]
            meta = {} if u_meta < p["incomplete_metadata_rate"] else {"unit": "arbitrary_units", "sensor_type": "synthetic"}
            base = {"synthetic": True, "source_id": f"synthetic-source-{s}", "seq": k, "true_time_s": _r(t),
                    "event_time_s": _r(t + skew), "value": _r(value), "is_outlier": is_out, "metadata": meta}
            recs.append(dict(base, record_id=f"s{s}-{k}", arrival_time_s=_r(t + delay), is_duplicate=False))
            if u_dup < p["duplicate_rate"]:
                recs.append(dict(base, record_id=f"s{s}-{k}-dup", arrival_time_s=_r(t + delay + 1 + 29 * u_dd), is_duplicate=True))
    recs.sort(key=lambda r: (r["arrival_time_s"], r["record_id"]))
    header = {
        "synthetic": True, "generator": GENERATOR_ID, "generator_version": GENERATOR_VERSION, "params": p, "seed": seed,
        "record_count": len(recs), "n_dropped_missing": dropped, "n_duplicates": sum(r["is_duplicate"] for r in recs),
        "n_outliers": sum(1 for r in recs if r["is_outlier"] and not r["is_duplicate"]),
        "limitations": LIMITATIONS, "content_sha256": canonical_hash({"p": p, "seed": seed, "records": recs}),
    }
    return {"header": header, "records": recs}


def stamp(header: dict) -> dict:
    """Header plus the (non-deterministic) generation timestamp, kept outside the content hash."""
    return dict(header, generated_at=datetime.now(timezone.utc).isoformat())
