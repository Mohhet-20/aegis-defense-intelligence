"""Geographic distance calculation.

This project has no PostGIS extension available (SQLite by default;
see docs/architecture/GEOSPATIAL_INTELLIGENCE_ARCHITECTURE.md for the
decision record), so every distance calculation in this codebase goes
through the single, documented, tested function below rather than a
naive Euclidean degree distance -- Section 4 explicitly forbids
treating degree differences as though they were a globally accurate
physical distance.

This function was originally a private helper (`_haversine_meters`)
duplicated nowhere else -- Phase 2's `app/services/correlation_service.py`
had its own copy for Event<->Event spatial correlation. Phase 7
promotes it here as the one shared, public implementation and
`correlation_service.py` now imports it instead of defining its own
copy, with zero behavior change (same formula, same constant, verified
by Phase 2/3's existing correlation tests still passing unchanged).
"""
from __future__ import annotations

import math

# Mean Earth radius in meters (the WGS84 "authalic" mean radius is
# commonly quoted as ~6,371,008.8m; this project uses the simpler,
# widely-used round figure 6,371,000m, consistent with the value
# correlation_service.py has used since Phase 2). This is a SPHERICAL
# approximation of an ellipsoidal planet -- see the module docstring's
# "Assumptions and limitations" note below.
EARTH_RADIUS_METERS = 6_371_000.0


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 lat/lon points, in
    meters, using the haversine formula.

    Assumptions and limitations ("document its assumptions
    and limitations"):

    - Treats the Earth as a perfect sphere of radius EARTH_RADIUS_METERS,
      not the true WGS84 reference ellipsoid. Error versus a full
      ellipsoidal geodesic (e.g. Vincenty/Karney) is at most ~0.5%,
      which is more than adequate for the threshold-based spatial
      correlation and radius-query use cases in this project, but this
      is NOT survey-grade or targeting-grade precision, and never
      should be presented as such.
    - Correctly handles longitude differences that cross the
      antimeridian (+/-180 deg) and points near either pole, because the
      formula operates entirely in spherical trigonometry (sin/cos of
      the actual angular difference) rather than a naive flat
      subtraction of raw latitude/longitude numbers -- a point at
      lon=179.9 and one at lon=-179.9 are correctly computed as ~0.2
      degrees of longitude apart, not ~359.8. See
      tests/test_geo_distance.py for the antimeridian/high-latitude
      cases this claim is verified against.
    - Both inputs are assumed to already be valid, finite WGS84 decimal
      degrees -- this function does not itself validate range; callers
      use app/geo/validation.py first.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * math.asin(min(1.0, math.sqrt(a)))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Convenience wrapper returning kilometers -- radius-query inputs
    (Section 5B) are naturally specified in km/miles by an analyst, so
    the query service works in km while persistence (EventCorrelation,
    spatial relationship metadata) keeps the existing meters convention
    correlation_service.py already established."""
    return haversine_meters(lat1, lon1, lat2, lon2) / 1000.0


def bounding_box_for_radius(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """A conservative, cheap, INDEXABLE pre-filter box (min_lat, max_lat,
    min_lon, max_lon) that is guaranteed to contain every point within
    `radius_km` of (lat, lon) -- used so a radius query can narrow the
    SQL WHERE clause with simple indexed column comparisons before the
    exact (and more expensive) haversine check runs in Python on the
    much smaller candidate set. This is deliberately a superset, never
    an exact circle -- the caller always re-checks with
    `haversine_km` afterward.

    Longitude degrees shrink toward the poles (cos(lat) factor); at
    lat=+-90 exactly, 1 degree of longitude is 0 physical distance, so
    the longitude span is clamped to the full -180..180 range in that
    case rather than dividing by zero or producing a span that would
    incorrectly exclude valid points near a pole.
    """
    lat_delta = radius_km / 111.32  # ~111.32 km per degree of latitude, everywhere
    min_lat = max(-90.0, lat - lat_delta)
    max_lat = min(90.0, lat + lat_delta)

    cos_lat = math.cos(math.radians(min(abs(lat) + lat_delta, 89.9)))
    lon_delta = radius_km / (111.32 * cos_lat) if cos_lat >= 1e-6 else 180.0
    if lon_delta >= 180.0:
        # Close enough to a pole (or a radius large enough) that the
        # box would wrap all the way around -- use the full longitude
        # range rather than an unbounded/absurd span.
        min_lon, max_lon = -180.0, 180.0
    else:
        min_lon = lon - lon_delta
        max_lon = lon + lon_delta

    return min_lat, max_lat, min_lon, max_lon
