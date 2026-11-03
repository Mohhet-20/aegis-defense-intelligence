"""Closed edge-inference adapter registry --
same discipline as app/sensors/adapters/registry.py and
app/connectors/registry.py: a fixed dict of known adapter keys, never a
dynamic import of an arbitrary string, and never execution of
downloaded code. An edge device's self-reported `inference_backends`
(app/models/device.py) is advisory/display-only; THIS registry is the
only thing that ever actually runs an adapter.

Inference results are explicitly kept SEPARATE from synchronization
state (Section 10, binding): `run_inference()` below returns a plain
result dict with its own provenance -- it is never itself a
`SyncRecord`. If a caller wants an inference result synced centrally,
it submits the result dict as an ordinary `inference_output` record
through the normal edge_sync_service path, same as any other capture.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional, Protocol

AVAILABILITY_STATES = ("available", "unavailable", "degraded")


class EdgeInferenceAdapter(Protocol):
    adapter_key: str
    model_version: str

    def availability(self) -> str: ...

    def run(self, input_data: dict) -> dict: ...


class UnknownEdgeAdapterError(ValueError):
    pass


class DeterministicSyntheticAdapter:
    """A SYNTHETIC, deterministic adapter -- explicitly NOT a trained
    model, same honest precedent as Phase 4's
    app/cv/adapters/mock_adapter.py. Given `{"brightness": float}` (or
    any dict with a numeric `"brightness"` key), it deterministically
    classifies "bright" vs "dim" by a fixed threshold. Exists so the
    edge inference PLUMBING (provenance linkage, availability states,
    the registry contract) can be exercised and tested honestly,
    without claiming any real detection capability. Always
    `available` -- it has no model file or GPU dependency."""

    adapter_key = "deterministic_synthetic_v1"
    model_version = "synthetic-1.0"
    BRIGHTNESS_THRESHOLD = 0.5

    def availability(self) -> str:
        return "available"

    def run(self, input_data: dict) -> dict:
        brightness = float(input_data.get("brightness", 0.0))
        label = "bright" if brightness >= self.BRIGHTNESS_THRESHOLD else "dim"
        confidence = min(1.0, abs(brightness - self.BRIGHTNESS_THRESHOLD) * 2)
        return {"label": label, "confidence": round(confidence, 4), "threshold": self.BRIGHTNESS_THRESHOLD}


_EDGE_INFERENCE_ADAPTERS: dict[str, Callable[[], "EdgeInferenceAdapter"]] = {
    "deterministic_synthetic_v1": DeterministicSyntheticAdapter,
}


def list_available_adapters() -> list[dict]:
    results = []
    for key, factory in _EDGE_INFERENCE_ADAPTERS.items():
        adapter = factory()
        results.append({"adapter_key": key, "model_version": adapter.model_version, "availability": adapter.availability()})
    return results


def get_adapter(adapter_key: str) -> "EdgeInferenceAdapter":
    factory = _EDGE_INFERENCE_ADAPTERS.get(adapter_key)
    if factory is None:
        raise UnknownEdgeAdapterError(f"'{adapter_key}' is not a registered edge inference adapter (known: {sorted(_EDGE_INFERENCE_ADAPTERS)})")
    return factory()


def run_inference(adapter_key: str, *, device_id: str, input_data: dict, now: Optional[datetime] = None) -> dict:
    """Runs the named adapter and returns a result dict carrying full
    provenance ("linked to model/device/input/timestamp
    provenance"). Raises `UnknownEdgeAdapterError` for an unregistered
    key -- never silently falls back to a different adapter."""
    adapter = get_adapter(adapter_key)
    if adapter.availability() != "available":
        raise RuntimeError(f"adapter '{adapter_key}' is currently '{adapter.availability()}', not available")
    generated_at = now or datetime.now(timezone.utc)
    output = adapter.run(input_data)
    return {
        "adapter_key": adapter_key,
        "model_version": adapter.model_version,
        "device_id": device_id,
        "input": input_data,
        "output": output,
        "generated_at": generated_at.isoformat(),
    }
