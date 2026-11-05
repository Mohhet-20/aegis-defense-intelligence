# Cross-Source Comparison (Section 11)

Status: implemented, live-verified, `app/services/cross_source_comparison_service.py` at 93%
test coverage in the 507-test backend suite (92% overall).

Cross-source comparison takes two already-fetched `Observation` rows -- typically from two
different sensors reporting on the same measurement type over overlapping time -- and reports
how they relate, without ever merging them into a single authoritative value. `compare()` is a
pure function with no database writes; persisting a reviewable link between the two
observations is a separate, explicit step.

## What `compare()` reports

`cross_source_comparison_service.compare(observation_a, observation_b, *, tolerance=None)`
returns a plain `dict` (parsed into `CrossSourceComparisonResponse` at the API boundary). It
never averages, merges, or picks a "winning" value between the two observations -- every field
describes the relationship, not a resolved answer:

- `same_measurement_type` -- whether `observation_type` matches on both sides.
- `units_compatible` -- whether both sides have a unit and `app.sensors.units.units_compatible()`
  considers them convertible.
- `value_b_converted_to_unit_a` / `delta` -- only populated when both observations carry a real
  `measurement_value`, both have a unit, the units are compatible, AND the conversion via
  `unit_lib.convert_unit()` succeeds; a raised `IncompatibleUnitError` is swallowed and `delta`
  stays `None` rather than the call failing.
- `conflicting` -- `True`/`False` only when `delta is not None` **and** a caller-supplied
  `tolerance` was given; with no tolerance, `conflicting` stays `None` ("not assessed"), never
  defaulting to `False`, which would falsely imply agreement was actually checked.
- `missing_a` / `missing_b` -- whether either observation lacks a numeric `measurement_value`
  at all.
- `time_gap_seconds` -- absolute gap between `observed_at_a` and `observed_at_b`, always
  computed regardless of whether the values themselves are comparable.
- `explanation` -- a human-readable sentence selected by `_explain()`, covering five distinct
  cases (missing value, type mismatch, incompatible units, conflicting-within-tolerance,
  conflicting-beyond-tolerance, and "no tolerance supplied") -- never a generic "mismatch"
  catch-all.
- `method_version` (`COMPARISON_METHOD_VERSION`, `"1.0"`) is stamped on every result, the same
  pattern `HEALTH_RULE_VERSION` uses in `docs/analytics/SENSOR_HEALTH.md`.

A disagreement beyond tolerance is explicitly explained as *"a disagreement between sources,
not evidence either one is wrong"* -- consistent with `docs/analytics/SOURCE_RELIABILITY.md`'s
rule that a correlated or conflicting pair is never treated as proof about the underlying
real-world event.

## Routes

| Method & path | Permission | Notes |
|---|---|---|
| `POST /cross-source-comparison/compare` | `OBSERVATION_READ` | Resolves both observation IDs (org-scoped, `404` if either is missing or belongs to another organization), calls `compare()`, returns the result. No database write. |
| `POST /cross-source-comparison/links` | `RELATIONSHIP_MANAGE` | Re-runs the same `compare()` call, then persists a link via `create_comparison_link()`. Returns `201` with an `EvidenceRelationshipResponse`. |

Both routes resolve observations through the same `_resolve_observation()` helper in
`app/api/routes/cross_source_comparison.py`, so a cross-tenant request behaves identically on
either route: `404`, not `403`, matching the tenant-isolation discipline each layer's
routes already follow.

## Persisting a link: reusing the evidence model

Section 11 asks to "link related observations using existing evidence-relationship models,"
and that is exactly what happens -- there is no new comparison table.

`create_comparison_link()` first wraps each `Observation` as an `Evidence` row via
`_get_or_create_observation_evidence()` (`evidence_type="sensor_observation"`,
`observation_id=observation.id`) -- idempotent: a second call for the same observation finds
and reuses the existing `Evidence` row rather than creating a duplicate. It then calls
`relationship_service.create_relationship()` with `source_ref_type="evidence"` /
`target_ref_type="evidence"` on both sides, `relationship_type="cross_source_comparison"`
(added to `RELATIONSHIP_TYPES` in `app/models/evidence_relationship.py` specifically for this
layer), `origin="analyst_created"` (the route always passes this; only an API-submitted link
is created this way, never a background job), `explanation=comparison["explanation"]`, and
`supporting_metadata=comparison` -- the full comparison dict, including the ISO-formatted
timestamps, is stored verbatim on the resulting row's `supporting_metadata` JSON column.

`relationship_service.create_relationship()` returns a **tuple**, `(relationship, created)` --
not just the relationship. `created=False` means an identical `(source, target,
relationship_type)` link already existed and was returned as-is rather than duplicated; the
route (`api/routes/cross_source_comparison.py`) only calls `audit_service.record()` (action
`cross_source_comparison.link`) and commits when `created` is `True`, so re-submitting the same
comparison link twice does not double-write an audit trail for a link that already exists.

A direct observation-to-observation link is deliberately not supported -- both sides go
through the `Evidence` wrapper, meaning a `cross_source_comparison` relationship is always
`evidence<->evidence` in storage, never `event<->event`, keeping it fully inside
`EvidenceRelationship`'s existing shape rather than requiring `Event`-side plumbing. This is
the same model documented in full in `docs/data/EVIDENCE_RELATIONSHIP_MODEL.md` and
`docs/analytics/EVIDENCE_GRAPH.md`; this layer adds one new `relationship_type` value to it and
nothing else.

Creating a link is never proof the two observations describe the same real-world event --
`IncomparableObservationsError` is raised (surfaced as `400`) only for the degenerate case of
comparing an observation to itself; a genuine conflict beyond tolerance is still linked and
stored, with `conflicting=True` sitting in `supporting_metadata` for an analyst to review via
the existing relationship review workflow (confirm/reject/uncertain), not resolved
automatically by this service.

See also `docs/api/SENSOR_API.md` for the full route table and `docs/analytics/SENSOR_HEALTH.md`
for the parallel "never collapse signals into a judgment" discipline this layer applies to
sensor operational health.
