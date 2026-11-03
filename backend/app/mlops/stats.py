"""Small, dependency-free statistics used by comparison and monitoring."""
from __future__ import annotations

import math
from typing import Optional, Sequence

Z95 = 1.959963984540054


def wilson_interval(successes: int, n: int, z: float = Z95) -> Optional[tuple[float, float]]:
    """Wilson score interval for a binomial proportion. Returns None when it is
    not justified (no trials, or counts inconsistent). It assumes independent
    samples; callers state that limitation."""
    if n <= 0 or successes < 0 or successes > n:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def intervals_overlap(a: Sequence[float], b: Sequence[float]) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])


def psi(reference_counts: Sequence[float], current_counts: Sequence[float], eps: float = 1e-4) -> Optional[float]:
    """Population Stability Index over matched bins/categories. Proportions are
    floored at ``eps`` so empty bins do not produce infinities. Returns None if
    either side has no observations."""
    rt, ct = float(sum(reference_counts)), float(sum(current_counts))
    if rt <= 0 or ct <= 0 or len(reference_counts) != len(current_counts):
        return None
    total = 0.0
    for r, c in zip(reference_counts, current_counts):
        rp, cp = max(r / rt, eps), max(c / ct, eps)
        total += (cp - rp) * math.log(cp / rp)
    return total


def mean_std(values: Sequence[float]) -> tuple[Optional[float], Optional[float]]:
    n = len(values)
    if n == 0:
        return None, None
    m = sum(values) / n
    if n == 1:
        return m, 0.0
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return m, math.sqrt(var)


def equal_width_edges(lo: float, hi: float, bins: int = 10) -> list[float]:
    if not math.isfinite(lo) or not math.isfinite(hi):
        raise ValueError("bin edges require finite bounds")
    if hi <= lo:
        hi = lo + 1.0  # constant feature: one non-degenerate range so binning is defined
    step = (hi - lo) / bins
    return [lo + step * i for i in range(bins + 1)]


def bin_counts(values: Sequence[float], edges: Sequence[float]) -> tuple[list[int], int, int]:
    """Counts per bin on fixed edges. Values below/above the range are placed in
    the first/last bin AND reported separately (underflow, overflow) so a shift
    out of the reference range stays visible."""
    bins = len(edges) - 1
    counts = [0] * bins
    under = over = 0
    for v in values:
        if v < edges[0]:
            under += 1
            counts[0] += 1
        elif v > edges[-1]:
            over += 1
            counts[-1] += 1
        else:
            idx = min(int((v - edges[0]) / (edges[-1] - edges[0]) * bins), bins - 1)
            counts[idx] += 1
    return counts, under, over
