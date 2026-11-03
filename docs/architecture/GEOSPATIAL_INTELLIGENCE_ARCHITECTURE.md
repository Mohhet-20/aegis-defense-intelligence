# Geospatial Intelligence Architecture (Phase 7)

**Status: IMPLEMENTED.** This document supersedes
`docs/architecture/GEOSPATIAL_CONTRACTS.md` (Phase 1's `PLANNED` sketch)
for everything actually built here. That file is left unmodified as the
historical record, consistent with how Phase 4/5/6 treated their own
superseded contract sketches.

## 1. Scope and non-goals

Phase 7 adds map-based situational awareness, bounded spatial/temporal
queries, historical playback, location-quality reporting, spatial
relationship discovery, and bounded export -- entirely as a **read-heavy,
decision-support layer on top of existing location-bearing tables**
(`Event`, `Sensor`, `Observation`, `Asset`). It adds **zero new
primary-entity tables** -- only columns (see
`docs/data/LOCATION_SCHEMA_AND_COORDINATE_SYSTEMS.md`) and one new
relationship kind layered onto Phase 3's existing `EvidenceRelationship`
model.

**Binding non-goals, unchanged from the specification's prohibited-scope
list and enforced throughout this phase's code and tests:**

- No autonomous targeting, engagement, or interception calculation of
  any kind.
- No automated hostile-intent or threat-level classification derived
  from geographic proximity, density, or clustering. `spatial_grid_counts`
  and `spatial_relationship_service` compute counts and distances only
  -- never a threat score, priority, or risk label.
- No fabricated live location ever presented as real. Every synthetic
  demo row carries `data_origin="synthetic_demo"`, surfaced to the
  frontend as `is_synthetic` and rendered with a visible
  `DataOriginBadge` -- never silently indistinguishable from a real
  observation.
- No silent extrapolation between two real recorded positions. The
  Timeline Explorer's playback steps through real stored records only
  (see `docs/analytics/TEMPORAL_EXPLORATION.md`); nothing interpolates
  a position or timestamp that was never recorded.

## 2. What's reused vs. what's new

| Concern | Reused from an earlier phase | New this phase |
|---|---|---|
| Coordinate storage | `Event`/`Sensor`/`Observation`/`Asset` already had `latitude`/`longitude` (Phase 1) | `GeoLocationMixin` extends every one of those four models with `coordinate_reference_system`, `location_origin`, `location_uncertainty_m`, `altitude_m`, `altitude_reference`, `location_source_observed_at`, `location_validation_status` -- one migration, zero new tables |
| Distance math | Phase 2's `correlation_service.py` had a private `_haversine_meters` | Promoted to the single shared `app/geo/distance.haversine_meters`/`haversine_km`/`bounding_box_for_radius`; `correlation_service.py` now imports it (zero behavior change, existing Phase 2/3 tests still pass unchanged) |
| Evidence/relationship model | Phase 3's `Evidence`, `EvidenceRelationship` (`REFERENCEABLE_TYPES = ("event", "evidence")`) | `spatial_relationship_service.py` reuses both unchanged -- a spatially-close `Observation` pair is wrapped as `sensor_observation`-type `Evidence` first (via the newly-public `evidence_service.get_or_create_observation_evidence`, idempotent), because `Observation` itself is not a referenceable type |
| Conflict/"same real-world event" determination | Phase 3's `conflict_service.py` | **Never duplicated.** `spatial_relationship_service.py` explicitly documents that it does not and will not decide whether two records describe the same real-world event -- that stays `conflict_service.py`'s job |
| Review/approve workflow for a generated relationship | Phase 3's existing `POST /relationships/{id}/review` route + `RELATIONSHIP_READ`/`RELATIONSHIP_MANAGE` permissions | None needed -- a spatial-relationship candidate is just an `EvidenceRelationship` row with `relationship_type="spatially_associated"` and `review_status="candidate"`, so the existing review endpoint works on it unchanged (confirmed by `test_generated_relationship_is_reviewable_via_existing_relationships_endpoint`) |
| Export infrastructure | Phase 2's `export_service.py` (`_FORMULA_PREFIXES` CSV-injection guard, `_csv_safe`) | `geo_export_service.py` reuses the identical formula-prefix guard and pattern, applied to GeoJSON/CSV instead of the existing tabular export |

## 3. New modules, by layer

- **`app/geo/`** -- pure-logic package, no database or FastAPI
  imports, fully unit-testable in isolation: `distance.py`
  (haversine + bounding-box prefilter) and `validation.py`
  (coordinate/quality classification). See
  `docs/data/LOCATION_PROVENANCE_AND_UNCERTAINTY.md`.
- **Services** (`app/services/`): `geo_query_service.py` (viewport/
  radius/spatial-grid), `geo_timeline_service.py` (temporal query,
  time buckets, gap detection), `location_quality_service.py`
  (quality findings + summary), `spatial_relationship_service.py`
  (candidate generation + listing), `geo_overview_service.py`
  (workspace landing-page aggregation), `geo_export_service.py`
  (GeoJSON/CSV).
- **Schemas**: `app/schemas/geospatial.py` -- every response shape
  for the above, including the `is_approximate` honesty wrapper used
  by every bounded-sample endpoint (`TimeBucketCountsResponse`,
  `TemporalGapsResponse`, `SpatialGridResponse`).
- **Routes**: `app/api/routes/geospatial.py` (overview, viewport,
  radius, quality, relationships), `geo_timeline.py`, `geo_analytics.py`
  (temporal gaps, spatial grid), `geo_export.py` -- 13 endpoints total,
  all under `/api/v1/geospatial/...`, all authenticated and
  permission-gated (see `docs/security/GEOGRAPHIC_DATA_GOVERNANCE.md`).
- **Frontend**: 7 pages under `frontend/src/pages/geo/`, routed under
  `/geospatial/*`, forming the Geospatial Intelligence Workspace (see
  Section 5).

## 4. Why no PostGIS / spatial index

This project's default database is SQLite (unchanged since Phase 1),
which has no spatial-index extension available in this environment.
Every query in this phase is therefore a **plain indexed-column
pre-filter (bounding box) followed by an exact in-Python haversine
check on the much smaller candidate set** -- `query_radius()` first
narrows with `bounding_box_for_radius()` (a conservative superset,
cheap `BETWEEN` comparisons on `latitude`/`longitude`), then
re-checks every candidate with `haversine_km()` before accepting it.
This is accurate (haversine error vs. a full ellipsoidal geodesic is
at most ~0.5%) but is a full-table-scan-within-the-bounding-box
pattern, not an indexed spatial query -- acceptable at this project's
data volumes (hundreds to low thousands of located rows), explicitly
not benchmarked at a larger scale, and documented honestly rather than
silently assumed to scale. A future phase moving to PostgreSQL could
swap in PostGIS without changing any caller's signature, since every
distance/bounding-box computation already goes through the single
`app/geo/distance.py` module.

## 5. The 7-section Geospatial Intelligence Workspace

| Section | Route | Backend surface |
|---|---|---|
| Overview | `/geospatial` | `GET /geospatial/overview` |
| Interactive Map Explorer | `/geospatial/map` | `GET /geospatial/viewport` |
| Timeline Explorer | `/geospatial/timeline` | `GET /geospatial/timeline`, `GET /geospatial/timeline/buckets` |
| Location Quality Center | `/geospatial/quality` | `GET /geospatial/quality/summary`, `GET /geospatial/quality/issues` |
| Spatial Relationship Explorer | `/geospatial/relationships` | `GET /geospatial/relationships`, `POST /geospatial/relationships/generate`, existing `POST /relationships/{id}/review` |
| Geographic Analytics Dashboard | `/geospatial/analytics` | `GET /geospatial/analytics/spatial-grid`, `GET /geospatial/analytics/temporal-gaps` |
| Export Center | `/geospatial/export` | `GET /geospatial/export/geojson`, `GET /geospatial/export/csv` |

See `docs/api/GEOSPATIAL_API.md` for the full request/response contract
of every route and `docs/testing/GEOSPATIAL_TEST_STRATEGY.md` for how
each was verified.

## 6. What Phase 7 does NOT do

- No live/streaming position feed -- every query is a point-in-time
  read against stored rows; there is no WebSocket, polling-push, or
  "live" marker that updates without a user-initiated refresh or
  viewport move.
- No track-visualization integration with Phase 5's `Track`/
  `TrackObservation` tables -- those remain image-space pixel
  trajectories over video, not geographic coordinates, and are out of
  this phase's scope (a reasonable future phase if/when tracks gain
  real-world georeferencing).
- No automatic merge of two spatially-close records into one --
  `spatial_relationship_service.generate_candidates()` only ever
  creates a reviewable `EvidenceRelationship` row; nothing in this
  phase writes to, deletes, or deduplicates the underlying `Event`/
  `Observation` rows themselves.
- No map tile provider or API key is bundled, hardcoded, or defaulted
  -- see `docs/operations/MAP_PROVIDER_CONFIGURATION.md`.
