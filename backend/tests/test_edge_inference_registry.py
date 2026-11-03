"""Unit tests for app/edge/inference/registry.py (Phase 8, Section
10): the closed adapter allow-list, availability states, provenance
linkage, and the explicit separation from synchronization state (a
result dict is never itself a SyncRecord)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.edge.inference.registry import (
    DeterministicSyntheticAdapter,
    UnknownEdgeAdapterError,
    get_adapter,
    list_available_adapters,
    run_inference,
)


def test_list_available_adapters_reports_the_closed_allow_list():
    adapters = list_available_adapters()
    keys = {a["adapter_key"] for a in adapters}
    assert keys == {"deterministic_synthetic_v1"}
    assert all(a["availability"] == "available" for a in adapters)


def test_get_unknown_adapter_raises():
    with pytest.raises(UnknownEdgeAdapterError):
        get_adapter("some_adapter_that_does_not_exist")


def test_run_inference_is_deterministic():
    result1 = run_inference("deterministic_synthetic_v1", device_id="dev-1", input_data={"brightness": 0.9})
    result2 = run_inference("deterministic_synthetic_v1", device_id="dev-1", input_data={"brightness": 0.9})
    assert result1["output"] == result2["output"]
    assert result1["output"]["label"] == "bright"


def test_run_inference_below_threshold_is_dim():
    result = run_inference("deterministic_synthetic_v1", device_id="dev-1", input_data={"brightness": 0.1})
    assert result["output"]["label"] == "dim"


def test_run_inference_carries_full_provenance():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = run_inference("deterministic_synthetic_v1", device_id="dev-42", input_data={"brightness": 0.7}, now=now)
    assert result["adapter_key"] == "deterministic_synthetic_v1"
    assert result["device_id"] == "dev-42"
    assert result["input"] == {"brightness": 0.7}
    assert result["generated_at"] == now.isoformat()
    assert "model_version" in result
    # the result is a plain dict -- never a SyncRecord or anything with
    # a sync_status (kept SEPARATE from sync state)
    assert "sync_status" not in result


def test_run_inference_rejects_unavailable_adapter(monkeypatch):
    monkeypatch.setattr(DeterministicSyntheticAdapter, "availability", lambda self: "unavailable")
    with pytest.raises(RuntimeError):
        run_inference("deterministic_synthetic_v1", device_id="dev-1", input_data={"brightness": 0.5})
