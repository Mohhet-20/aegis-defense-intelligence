"""Small, well-defined summary statistics.

`summarize` describes the spread of a metric across repeated runs (different
seeds). That spread is variability of the SIMULATED outcome. It is not a
confidence interval for any real-world quantity, and no confidence interval is
computed here."""
from __future__ import annotations

import math
from typing import Optional, Sequence


def quantile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear interpolation between order statistics (type 7)."""
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo))


def summarize(values: Sequence[Optional[float]]) -> dict:
    """Ignores None (undefined metric for that run) and reports how many were ignored."""
    vals = [float(v) for v in values if v is not None and math.isfinite(v)]
    out: dict = {"n": len(vals), "n_undefined": len(values) - len(vals), "mean": None, "sd": None, "sem": None,
                 "min": None, "max": None, "p10": None, "p50": None, "p90": None}
    if not vals:
        return out
    n = len(vals)
    mean = sum(vals) / n
    out.update(mean=mean, min=min(vals), max=max(vals))
    if n >= 2:
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
        out.update(sd=sd, sem=sd / math.sqrt(n))
    if n >= 5:  # quantiles of fewer than 5 values are not informative
        s = sorted(vals)
        out.update(p10=quantile(s, 0.1), p50=quantile(s, 0.5), p90=quantile(s, 0.9))
    return out


def relative_diff(base: Optional[float], alt: Optional[float]) -> tuple[Optional[float], Optional[str]]:
    """(relative difference, reason-if-undefined). Undefined when the baseline is 0 or a value is missing."""
    if base is None or alt is None:
        return None, "metric undefined in one of the runs"
    if base == 0:
        return None, "baseline is 0, so a relative difference is undefined"
    return (alt - base) / abs(base), None
