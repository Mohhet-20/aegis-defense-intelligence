# Spatial/Temporal Analytics (Phase 7)

**Status: IMPLEMENTED.** `geo_query_service.spatial_grid_counts()`,
`geo_timeline_service.time_bucket_counts()`/`temporal_gaps()`, surfaced
together as the Geographic Analytics Dashboard
(`pages/geo/GeographicAnalyticsDashboardPage.tsx`).

## 1. Binding principle: counts, never conclusions

This document exists specifically to hold the specification's
prohibited-scope rule in one place for every analytic this phase
computes: **every number here is a count of records in this
project's own data.** None of it is, or is ever combined into, a
threat score, a hostile-intent inference, a priority ranking, or any
other judgment about the real world. A grid cell with a high count
means "this project has many located records whose coordinates fall
in this cell" -- nothing more. A temporal gap means "this project
has no records for this record type in this interval" -- not "nothing
happened." No function in this phase takes a density or co-occurrence
figure as input and produces a causal or evaluative output; this is
enforced by code review of every function's return type (always a
count, a list of counts, or a distance/time figure) and is repeated
as a binding comment at the top of `spatial_grid_counts()` and in
`docs/analytics/SPATIAL_RELATIONSHIPS.md`.

## 2. Spatial grid aggregation

`spatial_grid_counts()` buckets every located record (reusing
`app/geo/validation.classify_validation_status()` to exclude invalid
locations, same as every other query in this phase) into fixed-size
lat/lon cells (`grid_resolution_degrees`, default
`settings.GEOSPATIAL_DEFAULT_GRID_RESOLUTION_DEGREES = 0.5`), using
`floor(lat/resolution)`/`floor(lon/resolution)` as the cell key. Each
returned `SpatialGridCellResponse` reports the cell's bounds, total
count, and a per-record-type breakdown (`record_types: dict`). Cells
are sorted by count descending; the frontend shows the first 12.

Bounded via `MAX_GRID_SAMPLE_ROWS = 5000` rows fetched **per record
type**, matching `location_quality_service`'s and
`geo_timeline_service`'s own bounded-sample discipline -- beyond that,
`is_approximate` is set `True` and carried to the API response via
`SpatialGridResponse`, never silently presented as a complete
aggregate.

## 3. Temporal bucket counts and gaps

See `docs/analytics/TEMPORAL_EXPLORATION.md` Section 4 for the full
mechanics -- both are surfaced on the same Geographic Analytics
Dashboard page, alongside the spatial grid, as the two halves of
"bounded spatial/temporal analytics" the specification's Section 9
requires.

## 4. Marker-category taxonomy (frontend, Map Explorer)

`MapExplorerPage.tsx`'s `categorize()` function assigns every located
record to exactly one display category, in this priority order
(highest-priority match wins):

1. **`synthetic`** -- `is_synthetic === true` (always shown distinctly,
   regardless of its validation status, so seeded demo data is never
   visually indistinguishable from real data).
2. **`uncertain`** -- has one or more non-empty `quality_findings`
   (e.g. `uncertainty_unavailable`, `stale_location_timestamp`) --
   note a record only reaches the frontend at all if
   `location_validation_status == "valid"`, so "uncertain" here always
   means "valid but imperfect," never "invalid."
3. **`validated`** -- `location_validation_status == "valid"` with no
   quality findings (computed live from the API response, never read
   from a stored/stale column -- see
   `docs/data/LOCATION_PROVENANCE_AND_UNCERTAINTY.md`).
4. **`derived`** / **`estimated_inferred`** -- reserved categories
   mapped from `location_origin`, included for taxonomic completeness
   per Section 7's required marker categories, but unreachable with
   today's real data since no service in this phase ever writes
   `location_origin="derived"` or `"estimated"`/`"inferred"` (see
   `docs/data/LOCATION_SCHEMA_AND_COORDINATE_SYSTEMS.md` Section 3).
5. **`unvalidated`** -- fallback for anything not matching the above.

Each category has a fixed color/label in `CATEGORY_STYLE` and a
visible legend -- never color-only encoding with no label. Clustering
(`clusterRecords()`) is a lightweight, from-scratch grid-bucketing
algorithm (cell size shrinks with zoom level), chosen over adding a
clustering library whose React 19 compatibility was unproven; a
cluster's click reveals an accessible member list below the map rather
than auto-expanding/zooming, a documented scope limit.

## 5. What this does NOT do

- No threat, risk, priority, or hostile-intent score derived from any
  count, cluster, density, or co-occurrence computed here -- see
  Section 1.
- No automatic flagging of a "hotspot" or "anomalous cluster" -- a
  high-count cell is reported as a number, with no threshold-based
  alerting layered on top.
- No predictive or forecasting output (e.g. "expected future
  activity") from any spatial or temporal aggregate.
- No cross-record-type correlation beyond simple per-cell/per-bucket
  counting -- e.g. a cell showing `{event: 7, observation: 3}` states
  only that both counts exist in that cell, never that the events and
  observations are related.
