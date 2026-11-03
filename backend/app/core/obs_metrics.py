"""Small in-process metrics registry.

No metrics stack existed in the repository, so this is a deliberately small,
dependency-free abstraction rather than a new heavyweight dependency.

Guarantees (each is covered by tests):
 * Metrics are declared up front in CATALOG with a fixed label-name tuple.
   Unknown metric names or label names are rejected, so a caller cannot
   invent a high-cardinality label such as ``user_id`` or ``filename``.
 * Label VALUES are normalised (allow-listed characters, length-capped).
 * Each metric has a hard cap on distinct label combinations
   (``METRICS_MAX_SERIES_PER_METRIC``). Beyond it, new combinations are folded
   into a single ``other`` series and counted in ``overflow_total`` -- memory
   is bounded no matter what is fed in.
 * Values are PROCESS-LOCAL and reset on restart. With several workers each
   keeps its own numbers; nothing here aggregates across processes.
 * Components that do not exist (job queue, DB-failure counters, host
   resource saturation) are listed in ``UNAVAILABLE`` and are never reported
   as zero.
"""
from __future__ import annotations

import math
import re
import threading
import time
from typing import Iterable, Optional

from app.core.config import get_settings

DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

# name -> (kind, help, label names, buckets)
CATALOG: dict[str, tuple[str, str, tuple[str, ...], tuple[float, ...]]] = {
    "http_requests_total": ("counter", "HTTP requests handled, by method, route template and status class.", ("method", "route", "status_class"), ()),
    "http_request_duration_seconds": ("histogram", "HTTP request latency in seconds, by method and route template.", ("method", "route"), DEFAULT_BUCKETS),
    "inference_jobs_total": ("counter", "Inference jobs finished in this process, by outcome.", ("outcome",), ()),
    "inference_job_duration_seconds": ("histogram", "Inference job wall-clock duration in seconds.", ("job_type",), DEFAULT_BUCKETS),
    "mlops_experiment_runs_total": ("counter", "Experiment runs finished in this process, by task and outcome.", ("task", "outcome"), ()),
    "mlops_experiment_duration_seconds": ("histogram", "Experiment run duration in seconds, by task.", ("task",), DEFAULT_BUCKETS),
    "mlops_review_signals_total": ("counter", "Review signals created in this process, by category and severity.", ("category", "severity"), ()),
    "mlops_artifact_verifications_total": ("counter", "Model artifact verifications, by outcome.", ("outcome",), ()),
    "metrics_label_overflow_total": ("counter", "Label combinations folded into 'other' because of the series cap.", ("metric",), ()),
}

UNAVAILABLE = {
    "job_queue_depth": "There is no job queue: jobs run in the API process, so queue depth does not exist.",
    "database_operation_failures": "Database errors are not counted by a dedicated instrument; they surface as 5xx request counts only.",
    "storage_operation_failures": "Storage operations are not instrumented individually; readiness reports current storage reachability.",
    "host_resource_saturation": "CPU, memory and disk saturation are not measured by the application process.",
    "model_version_usage": "Per-model-version usage is not exported as a metric (model ids would be unbounded labels); see inference job rows instead.",
    "cross_process_aggregation": "Counters are per process and reset on restart; they are not aggregated across workers.",
}

_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
_VALUE_OK = re.compile(r"[^A-Za-z0-9_./{}:\-]")


def norm_label(value: object, max_len: int = 80) -> str:
    text = _VALUE_OK.sub("_", str(value))[:max_len]
    return text or "none"


def status_class(code: int) -> str:
    return f"{code // 100}xx" if 100 <= code <= 599 else "other"


class MetricsRegistry:
    def __init__(self, max_series: Optional[int] = None) -> None:
        self._lock = threading.Lock()
        self._max_series = max_series
        self._counters: dict[str, dict[tuple, float]] = {}
        self._hist: dict[str, dict[tuple, dict]] = {}
        self.started_at = time.time()

    @property
    def max_series(self) -> int:
        return self._max_series if self._max_series is not None else get_settings().METRICS_MAX_SERIES_PER_METRIC

    def enabled(self) -> bool:
        return get_settings().METRICS_ENABLED

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._hist.clear()
            self.started_at = time.time()

    def _key(self, name: str, kind: str, labels: dict) -> tuple:
        spec = CATALOG.get(name)
        if spec is None or spec[0] != kind:
            raise KeyError(f"unknown {kind} metric: {name}")
        label_names = spec[2]
        if set(labels) != set(label_names):
            raise KeyError(f"metric {name} takes labels {label_names}, got {tuple(sorted(labels))}")
        values = []
        for ln in label_names:
            v = labels[ln]
            if ln == "method":
                v = str(v).upper()
                v = v if v in _ALLOWED_METHODS else "OTHER"
            values.append(norm_label(v))
        return tuple(values)

    def _admit(self, store: dict, name: str, key: tuple) -> tuple:
        series = store.setdefault(name, {})
        if key in series or len(series) < self.max_series:
            return key
        overflow = self._counters.setdefault("metrics_label_overflow_total", {})
        overflow[(name,)] = overflow.get((name,), 0.0) + 1
        return tuple("other" for _ in key)

    def inc(self, name: str, labels: dict, value: float = 1.0) -> None:
        if not self.enabled():
            return
        if not math.isfinite(value) or value < 0:
            return
        key = self._key(name, "counter", labels)
        with self._lock:
            key = self._admit(self._counters, name, key)
            series = self._counters.setdefault(name, {})
            series[key] = series.get(key, 0.0) + value

    def observe(self, name: str, labels: dict, value: float) -> None:
        if not self.enabled() or not math.isfinite(value) or value < 0:
            return
        key = self._key(name, "histogram", labels)
        buckets = CATALOG[name][3]
        with self._lock:
            key = self._admit(self._hist, name, key)
            series = self._hist.setdefault(name, {})
            h = series.get(key)
            if h is None:
                h = series[key] = {"count": 0, "sum": 0.0, "buckets": [0] * len(buckets)}
            h["count"] += 1
            h["sum"] += value
            for i, upper in enumerate(buckets):
                if value <= upper:
                    h["buckets"][i] += 1

    # ---- read side -------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            out: dict = {}
            for name, (kind, help_text, label_names, buckets) in CATALOG.items():
                if kind == "counter":
                    series = self._counters.get(name, {})
                    out[name] = {"type": "counter", "help": help_text, "labels": list(label_names),
                                 "series": [{"labels": dict(zip(label_names, k)), "value": v} for k, v in sorted(series.items())]}
                else:
                    series = self._hist.get(name, {})
                    out[name] = {"type": "histogram", "help": help_text, "labels": list(label_names), "buckets": list(buckets),
                                 "series": [{"labels": dict(zip(label_names, k)), "count": h["count"], "sum": round(h["sum"], 6),
                                             "bucket_counts": list(h["buckets"])} for k, h in sorted(series.items())]}
            return out

    def to_prometheus(self) -> str:
        lines: list[str] = []
        for name, meta in self.snapshot().items():
            lines.append(f"# HELP {name} {meta['help']}")
            lines.append(f"# TYPE {name} {meta['type']}")
            for s in meta["series"]:
                lab = ",".join(f'{k}="{v}"' for k, v in s["labels"].items())
                if meta["type"] == "counter":
                    lines.append(f"{name}{{{lab}}} {s['value']}")
                else:
                    for upper, c in zip(meta["buckets"], s["bucket_counts"]):
                        lines.append(f'{name}_bucket{{{lab},le="{upper}"}} {c}')
                    lines.append(f'{name}_bucket{{{lab},le="+Inf"}} {s["count"]}')
                    lines.append(f"{name}_sum{{{lab}}} {s['sum']}")
                    lines.append(f"{name}_count{{{lab}}} {s['count']}")
        return "\n".join(lines) + "\n"

    def series_count(self, name: str) -> int:
        with self._lock:
            return len(self._counters.get(name, {})) + len(self._hist.get(name, {}))


def estimate_quantile(buckets: Iterable[float], bucket_counts: list[int], count: int, q: float) -> Optional[float]:
    """Upper-bound quantile estimate from cumulative histogram buckets: the
    smallest bucket bound containing the q-th observation. None when there are
    no observations or the quantile falls beyond the last bucket."""
    if count <= 0:
        return None
    target = q * count
    for upper, c in zip(buckets, bucket_counts):
        if c >= target:
            return upper
    return None


registry = MetricsRegistry()
