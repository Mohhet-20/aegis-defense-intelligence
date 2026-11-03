# Edge Inference (Phase 8)

**Status: IMPLEMENTED, tested, SIMULATED ONLY.** `app/edge/inference/registry.py`
is the closed adapter registry for local (on-device) inference, modeled
after the same pattern this project already uses twice: Phase 4's
`app/cv/adapters/mock_adapter.py`/CV adapter registry, and
`app/sensors/adapters/registry.py`/`app/connectors/registry.py`. Nothing
here claims real, trained-model detection capability.

## 1. The adapter registry pattern

`_EDGE_INFERENCE_ADAPTERS` is a **fixed Python dict** mapping a known
`adapter_key` string to a factory callable -- never a dynamic import of an
arbitrary string, and never execution of downloaded code.
`get_adapter(adapter_key)` raises `UnknownEdgeAdapterError` for anything
not in that dict; there is no fallback to "closest match" or silent
substitution. This is the same closed-registry discipline every other
adapter surface in this codebase follows, specifically so an edge device's
self-reported capability list can never cause the server (or, in a real
deployment, the device) to run code it didn't ship with.

## 2. The one synthetic adapter, and why it's synthetic

`DeterministicSyntheticAdapter` (`adapter_key = "deterministic_synthetic_v1"`,
`model_version = "synthetic-1.0"`) is the only registered adapter. Given
`{"brightness": <float>}`, it deterministically classifies `"bright"` vs
`"dim"` against a fixed threshold (`BRIGHTNESS_THRESHOLD = 0.5`) and
returns a confidence derived from distance to that threshold. It is
**explicitly not a trained model** -- the same honest precedent Phase 4's
`mock_adapter.py` set for computer vision. It exists purely to exercise the
plumbing (the registry contract, availability states, provenance linkage)
honestly, without claiming any real detection capability the project
doesn't actually have.

## 3. Availability states

`AVAILABILITY_STATES = ("available", "unavailable", "degraded")`. Every
adapter implements `availability() -> str`.
`DeterministicSyntheticAdapter.availability()` always returns `"available"`
-- it has no model file, no GPU dependency, and nothing that could make it
unavailable in this environment. `run_inference()` checks availability
before running and raises a plain `RuntimeError` if an adapter reports
anything other than `available`, rather than running anyway and producing
a misleading result.

## 4. Provenance fields

`run_inference(adapter_key, *, device_id, input_data, now=None)` returns a
plain dict carrying full provenance, never a bare output value:

| Field | Meaning |
|---|---|
| `adapter_key` | Which registered adapter produced this result. |
| `model_version` | The adapter's own version string. |
| `device_id` | Which device requested the inference. |
| `input` | The exact input dict the adapter was given. |
| `output` | The adapter's own result (`label`, `confidence`, `threshold` for the synthetic adapter). |
| `generated_at` | ISO timestamp, defaulting to `datetime.now(timezone.utc)` unless a caller injects `now` (used by tests for determinism). |

## 5. Explicit separation from sync state

**Binding, stated in the module docstring:** an inference result dict is
never itself a `SyncRecord`. `run_inference()`'s return value is a plain
dict with its own provenance envelope, entirely independent of
`app/models/sync_record.py`. If a caller wants an inference result synced
to the central system, it submits that result dict as the `payload` of an
ordinary `inference_output`-type `SyncRecordEnvelope`, through the exact
same `edge_sync_service` path as any other capture (`observation_capture`,
`event_capture`, `annotation`). There is no shortcut that writes a
`SyncRecord` directly from `run_inference()`'s return value -- the two
concerns (running a local model, and syncing a record) are kept
architecturally separate so that, for example, a device could run
inference purely for local decision-making without ever syncing the
result, or re-run inference without that act alone creating sync state.

## 6. How a real model would be added later

Extending the registry, never dynamic code loading:

1. Implement a class satisfying the `EdgeInferenceAdapter` protocol
   (`adapter_key`, `model_version`, `availability()`, `run(input_data)`).
2. Add it to the `_EDGE_INFERENCE_ADAPTERS` dict with its own
   `adapter_key`.
3. Nothing else in `edge_sync_service.py`, the sync protocol, or the
   `SyncRecord`/`SyncConflict` models needs to change -- a new adapter is
   purely additive to the registry, same as adding a new CV/sensor
   adapter in the existing registries.

What this phase deliberately does **not** provide: any mechanism for a
device to upload or register a new model/adapter dynamically, any
model-weight file handling, and any capability for `inference_backends`/
`model_manifest` (a device's self-reported capability metadata) to cause a
different adapter to actually run -- those fields are advisory/display-only
(see `app/models/device.py`), never used for authorization or dispatch.

## 7. Known gaps

- Exactly one adapter is registered; no second, trained adapter exists in
  this codebase (consistent with Phase 4's own single-real-adapter
  state for computer vision).
- No model-file or weight-management story exists for a future real
  adapter -- this phase doesn't need one, since its one adapter has no
  file to manage.
- `availability()` is static (`"available"` always) for the only
  registered adapter -- a real adapter's `availability()` reporting
  `"unavailable"`/`"degraded"` (e.g. missing hardware, overheating) is
  untested beyond the protocol contract itself.
