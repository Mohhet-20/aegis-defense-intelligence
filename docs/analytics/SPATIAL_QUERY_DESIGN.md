# Spatial Query Design

**Status: IMPLEMENTED.** `app/services/geo_query_service.py`.

## 1. Two query shapes, one shared fetch primitive

`GET /geospatial/viewport` (bounding box) and `GET /geospatial/radius`
(center point + radius) both route every record type's rows through
the same `fetch_record_type()` helper, then diverge only in their
filter/scoring logic:

- **Viewport** (`query_viewport`): a plain indexed `BETWEEN` on
  `latitude` and a longitude filter (see Section 2) -- no distance
  math, since a bounding box doesn't need any.
- **Radius** (`query_radius`): first narrows with
  `app/geo/distance.bounding_box_for_radius()` (a conservative,
  cheap, indexable superset box), then exact-checks every candidate
  in the much smaller result set with `haversine_km()`, keeping only
  rows whose true great-circle distance is within the requested
  radius. Results carry a real `distance_m`, sorted nearest-first.

## 2. Antimeridian handling

A bounding box whose `min_lon > max_lon` describes a box that *crosses*
+/-180 degrees (e.g. `min_lon=170, max_lon=-170`, meaning "everything
east of 170E or west of 170W"). `_normalize_lon_ranges()` detects this
and returns **one or two** sub-ranges, which `_lon_filter()` combines
with `OR` in the SQL `WHERE` clause -- never a single `BETWEEN`, which
would silently match nothing (since `min > max` makes every row fail)
or the wrong half of the globe. `BoundsSearched.crossed_antimeridian`
reports this back to the caller so a map UI can render the split
correctly rather than guessing. Verified by
`tests/test_geo_query_service.py`'s antimeridian cases and
`tests/test_geo_distance.py`'s equivalent haversine-formula cases.

## 3. Authorization and tenant isolation

Every query function takes `organization_id` as a required, non-optional
parameter and every underlying SQL statement filters on it explicitly
(`model.organization_id == organization_id`) -- the same per-call
discipline each layer's service functions use (the
documented, not-yet-framework-enforced tenant model, the job).
The route layer additionally requires `Permission.GEOSPATIAL_READ` on
every read endpoint (see `docs/security/GEOGRAPHIC_DATA_GOVERNANCE.md`).
A cross-tenant query returns an empty/zero-match result, never another
tenant's data and never a `403` that would leak the other tenant's
existence.

## 4. Result-size bounding -- never an unrestricted full-dataset download

- `settings.GEOSPATIAL_MAX_RESULTS` (default 500) hard-caps every
  query's returned item count, regardless of what a caller requests via
  `max_results` (`min(requested, settings.GEOSPATIAL_MAX_RESULTS)` --
  a caller can only ask for *fewer*, never more).
  `fetch_record_type()` additionally over-fetches by a bounded
  multiple (`limit * 3`, capped) so validity-filtering doesn't
  under-fill a page, never unbounded.
- `settings.GEOSPATIAL_MAX_RADIUS_KM` (default 5000 km) rejects an
  unreasonably large radius outright (`ValueError`, surfaced as
  `400`) rather than letting a request silently scan an entire
  hemisphere.
- `settings.GEOSPATIAL_MAX_TIME_RANGE_DAYS` (365, enforced by
  `geo_timeline_service`, see `docs/analytics/TEMPORAL_EXPLORATION.md`)
  bounds how wide a time filter a caller can combine with a spatial one.
- Every response states **what it searched** (`bounds_searched`,
  `radius_km`/`center_latitude`/`center_longitude`,
  `time_range_searched`, `record_types_searched`) and **whether it was
  truncated** (`truncated: bool`, `total_matched` vs. `returned_count`)
  -- Section 5A's "prevent unrestricted full-dataset downloads" made
  honest and visible, never a silent partial result presented as
  complete.

## 5. Per-record-type timestamp selection

`Event`/`Observation` support an explicit choice between `observed_at`
(when the thing happened) and `ingested_at` (when this system received
it) via `timestamp_type`; `Sensor`/`Asset` have exactly one option,
their own `created_at`, exposed as `"registered_at"` since it describes
registry entry, not an occurrence. `_time_filter()` uses a half-open
interval (`since <= t < until`) so adjacent time windows never
double-count or gap a boundary record. `ingested_at` can itself be
`NULL` on a legacy row -- `_timestamp_and_type()` falls back to
`observed_at` and reports the *actual* type used in
`timestamp_type`, rather than silently returning a timestamp whose
reported type doesn't match what was actually used.

## 6. Missing/invalid locations are excluded, and the exclusion count is reported

A record with `latitude IS NULL` is filtered out by the SQL query
itself and never fetched. A record whose coordinates *are* present but
fail `app/geo/validation.classify_validation_status()` (invalid range,
non-finite, unsupported CRS) is fetched but excluded from `items`, with
the exclusion counted in `missing_or_invalid_location_count` -- see
`docs/data/LOCATION_PROVENANCE_AND_UNCERTAINTY.md` Section 3 for why
these two counts are deliberately not the same number.

## 7. What this does NOT do

- No spatial index (see
  `docs/architecture/GEOSPATIAL_INTELLIGENCE_ARCHITECTURE.md` Section 4)
  -- a bounding-box pre-filter plus an exact in-Python check, not an
  indexed geometry query.
- No polygon/shape queries -- only axis-aligned bounding box and
  circular radius.
- No cross-organization query, ever, at any permission level.
- No result ever includes a record whose location is missing or
  invalid -- those are reported only as a count, never as a point
  plotted at a guessed or default position.
