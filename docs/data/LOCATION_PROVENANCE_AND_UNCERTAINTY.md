# Location Provenance and Uncertainty

**Status: IMPLEMENTED.**

## 1. Validation is computed live, not read off the stored column

Every table's `location_validation_status` column (added by this
layer's migration) exists, but **no query, quality-report, or map
endpoint in this codebase reads it.** Instead, every one of
`geo_query_service.to_located_record()`, `location_quality_service`,
and `spatial_relationship_service` calls
`app/geo/validation.classify_validation_status()` (or
`validate_coordinates()`) fresh, every time, directly from the row's
current `latitude`/`longitude`/`coordinate_reference_system`.

This is deliberate, not an oversight: the stored column is NULL on
every row written beforehand's services existed (no
pre-original write path -- event/sensor/observation ingestion, asset
creation -- has ever populated it), and would stay NULL on an ordinary
new row created through any of those unmodified paths today, since
none of them were changed to write it either. Recomputing live from
the three raw columns is cheap (a handful of comparisons, zero
additional I/O) and is **always correct**, rather than being only as
fresh as the last time something happened to write the stored column.
See `app/services/geo_query_service.py`'s module docstring for the
full reasoning.

## 2. Missing vs. invalid vs. uncertain: three distinct concepts

| Concept | How it's represented | Never confused with |
|---|---|---|
| **Missing** | `latitude is None` (and therefore `longitude is None`) -- never written, never defaulted to `(0.0, 0.0)` | Invalid -- a missing location has no coordinates to be invalid |
| **Invalid** | Present but unusable: out of WGS84 range, non-finite (`NaN`/`inf`), or an unsupported CRS (`app/geo/validation.py`'s `FINDING_INVALID_RANGE`/`FINDING_NON_FINITE`/`FINDING_UNSUPPORTED_CRS`) | Missing -- an invalid location IS present data, just not usable data |
| **Uncertain** | `location_uncertainty_m is None` -- read as **unknown uncertainty**, never as zero uncertainty (`FINDING_UNCERTAINTY_UNAVAILABLE`, informational, not an error) | A location with a real but large uncertainty value, which is simply reported as-is, not flagged |

A location can be simultaneously valid, present-but-stale, and
uncertainty-unknown -- `validate_coordinates()` returns **every**
applicable finding, not just the first, for a usable coordinate (the
informational findings `FINDING_STALE_SOURCE_TIMESTAMP` and
`FINDING_UNCERTAINTY_UNAVAILABLE` can both appear alongside
`FINDING_VALID`). The three disqualifying findings
(`invalid_range`/`non_finite`/`unsupported_crs`) are mutually
exclusive with `valid` and are returned alone, since an unusable
coordinate has nothing further to report.

## 3. The `missing_or_invalid_location_count` convention

Every spatial query response (`GeospatialQueryResponse.missing_or_invalid_location_count`)
counts only **present-but-invalid** coordinates that were fetched and
then excluded -- never NULL-coordinate rows. This is because
`geo_query_service.fetch_record_type()`'s own SQL `WHERE` clause
filters out NULL-coordinate rows at the database level
(`model.latitude.is_not(None)`), so a genuinely missing-location row
is never fetched in the first place and therefore can't be counted as
"excluded." Truly-missing counts are a separate, exact SQL `COUNT`
living in `location_quality_service.quality_summary()`'s
`missing_count` field.

This distinction is load-bearing and intentionally asymmetric between
the two services:

- `geo_query_service`/`geo_overview_service` (`missing_or_invalid_location_count`/
  `missing_or_invalid_location_total`): counts present-but-invalid rows
  only, because missing rows are never fetched.
- `location_quality_service` (`missing_count`): a direct `COUNT(*)
  WHERE latitude IS NULL`, independent of any fetch/exclusion logic.

Confirmed correct, established behavior via
`tests/test_geo_query_service.py::test_viewport_excludes_invalid_range_or_unsupported_crs`
and `tests/test_geo_overview_service.py`, whose own initial
assumption (that a NULL-coordinate row would count toward
`missing_or_invalid_location_total`) was wrong and was corrected
during test authoring to use a present-but-invalid row instead -- not
a defect in the application.

## 4. Uncertainty: never invented

`location_uncertainty_m` is written only when a source or a documented
computation actually supplies a figure. No service
computes or backfills a fabricated uncertainty value for a record that
lacks one -- `FINDING_UNCERTAINTY_UNAVAILABLE` exists specifically so
"unknown" is always visibly distinguishable from "zero/perfect"
positional accuracy, both in the API response (`quality_findings`
array on a `LocatedRecordResponse`) and in the Location Quality
Center's per-row findings column.

## 5. Staleness

`FINDING_STALE_SOURCE_TIMESTAMP` compares a record's own occurrence
timestamp (its `observed_at`, passed into `validate_coordinates()` as
`location_source_observed_at`) against
`settings.GEOSPATIAL_STALE_LOCATION_AFTER_SECONDS` (7 days, default).
This is informational only (`is_error=False`) -- a stale location is
still plotted and still included in query results, just flagged so an
analyst knows the coordinate may no longer reflect current reality.
There is no dedicated `location_source_observed_at` database column;
the record's own existing occurrence timestamp is reused for this
purpose, consistent with the specification's "reuse what already exists"
discipline.

## 6. What this does NOT do

- No automatic re-validation or background job re-checks stored rows
  -- validation is always computed on read, so there is nothing to
  "re-run."
- No positional-accuracy estimation from other signals (e.g. GPS HDOP,
  sensor spec sheets) -- uncertainty is exactly what the source
  supplied, or `None`.
- No automatic promotion of a `source_reported` location to
  `validated` -- `location_origin` is written once at creation time
  (`source_reported` for every real write path today) and nothing in
  this layer changes it afterward.
- No conflicting-source-coordinate detection as a single-record
  finding -- comparing two independent sources' coordinates for the
  *same* real-world thing is a cross-record concern, explicitly
  deferred to `app/services/spatial_relationship_service.py` (see
  `docs/analytics/SPATIAL_RELATIONSHIPS.md`), not something
  `app/geo/validation.py` can determine from one row alone.
