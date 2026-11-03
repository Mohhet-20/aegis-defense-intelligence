# Multisensor Contracts — Planned (Phase 3, Phase 6)

**Status: PLANNED for the correlation/fusion/quality logic. The
underlying `Sensor` and `Observation` storage shapes are REAL (Phase 1
ships working tables and registry endpoints) — what's planned is
everything that reasons *across* observations.**

## What Phase 1 actually ships

- `Sensor`: identity, type, source/device association, operational
  status, `last_seen_at`, optional location, optional capability
  metadata. Real registry CRUD at `/api/v1/sensors`.
- `Observation`: sensor/source id, observation timestamp, observation
  type, structured measurement payload, optional location, quality
  metadata field (present, not yet populated by any real quality
  computation), provenance, processing status. Real list endpoint at
  `/api/v1/observations`; populated only via seed data for
  demonstration.

## What Phase 6 (Sensor and Observation Analytics) will add

- **Sensor health computation** from `last_seen_at` + a configured
  heartbeat expectation — not implemented in Phase 1 (there is no
  real sensor sending heartbeats yet).
- **Observation-quality scoring** — the `quality_metadata` JSON field
  exists on the model now specifically so this can be added without a
  migration; it is `null`/empty on every seed row today.
- **Timestamp normalization** across sensors reporting in different
  formats or clock-skewed sources.
- **Cross-source association** — recognizing that two observations from
  different sensors likely describe the same real-world object/event.

## What Phase 3 (Multisource Intelligence Fusion) will add

- **Source reliability** as a configured, queryable property of
  `DataSource` (the column exists; Phase 1 does not compute or display
  a derived reliability score from ingestion history).
- **Fusion services** that combine correlated observations into a
  higher-confidence conclusion, with explicit conflict-resolution logic
  when two sources disagree — conflicts must be surfaced, never
  silently averaged away.
- **Evidence lineage** — every fused conclusion must be traceable back
  to the specific observations/events that produced it.

## Binding principles (apply from Phase 3/6 onward)

- Do not silently fuse observations reported in incompatible units,
  coordinate systems, or timestamp formats. A fusion step that can't
  normalize two inputs confidently must flag the mismatch, not guess.
- Do not treat two observations that are actually correlated (e.g. two
  sensors triggered by the same underlying event) as independent
  evidence that multiplies confidence — that overstates certainty.
  Correlation must be assessed before confidence is combined.
- A missing location is `None`/absent, never `(0.0, 0.0)` — this
  applies to `Asset`, `Sensor`, and `Event` already in Phase 1's
  schema (all location fields are nullable, with no default
  coordinate), and will apply identically to any future observation or
  fused-track location.

## What Phase 1 does NOT do

No correlation, fusion, or cross-sensor reasoning runs anywhere in this
codebase yet. `Observation.quality_metadata` and `DataSource`'s
reliability configuration are schema-only placeholders.
