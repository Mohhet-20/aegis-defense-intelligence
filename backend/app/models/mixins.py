"""Shared mixins for domain models."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

# Phase 7, Section 3A: the only coordinate reference system any real
# connector or seed script in this project actually produces. A value
# outside this tuple is never silently treated as WGS84 -- see
# app/geo/validation.py's "unsupported_crs" finding -- because Section 3
# explicitly forbids "silently interpreting projected coordinates as
# latitude/longitude." No conversion pipeline exists for a second CRS
# because nothing in this codebase has ever needed one; see
# docs/data/LOCATION_SCHEMA_AND_COORDINATE_SYSTEMS.md.
SUPPORTED_COORDINATE_REFERENCE_SYSTEMS = ("WGS84",)

# Section 3A: where a stored coordinate actually came from. "source_reported"
# is the default for anything a connector/seed script supplies directly
# (matches every pre-Phase-7 row's implicit meaning); "validated" means
# app/geo/validation.py has checked it and found no issue; "derived"/
# "estimated"/"inferred" are reserved for a future capability that
# computes a location FROM other records rather than receiving one
# directly -- nothing in Phase 7 writes these three yet (see
# docs/data/LOCATION_PROVENANCE_AND_UNCERTAINTY.md's "what this does NOT
# do" section), but the vocabulary exists now so a future phase never
# has to overload "source_reported" to mean something it doesn't.
LOCATION_ORIGINS = ("source_reported", "validated", "derived", "estimated", "inferred")

# findings app/geo/validation.py can produce for a PRESENT
# coordinate pair. A record with no coordinates at all (latitude is
# None) never gets one of these written to it -- "missing" is read
# directly off `latitude is None`, never stored as a status string,
# so there is exactly one place in the codebase that can say a
# location is missing (see GeoLocationMixin's own docstring below).
LOCATION_VALIDATION_STATUSES = ("valid", "invalid_range", "non_finite", "unsupported_crs")

ALTITUDE_REFERENCES = ("wgs84_ellipsoid", "msl", "agl")


class GeoLocationMixin:
    """Optional WGS84 decimal-degree coordinates, extended in Phase 7
    with the provenance/uncertainty metadata
    needed to distinguish a source-reported location from a validated,
    derived, or missing one. Section 7's original rule still
    holds and is now load-bearing for every field below, not just
    latitude/longitude: "a missing location is not a location of zero
    latitude and longitude" -- every column here is nullable with NO
    default value that could be mistaken for a real measurement, and
    `app/schemas/common.py` validates range only when a value is
    actually present.

    This mixin is deliberately still a flat pair of columns on each
    owning table (Event/Asset/Sensor/Observation), not a separate
    `locations` table with a foreign key -- Section 3B's "prefer...a
    compatible shared location model over duplicating coordinate fields
    across every table" is satisfied by every table sharing this ONE
    mixin definition (a schema/behavior change here applies identically
    everywhere), while avoiding the join-heavy rewrite a separate table
    would force on every existing query in Phases 1-6. See
    docs/architecture/GEOSPATIAL_INTELLIGENCE_ARCHITECTURE.md for the
    full reasoning."""

    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Stated, never assumed (Section 3A). Defaults to "WGS84" because
    # every coordinate ever written in this codebase before Phase 7 was
    # implicitly WGS84; the column exists so a future non-WGS84 source
    # has somewhere honest to say so rather than being silently
    # mis-read.
    coordinate_reference_system: Mapped[str] = mapped_column(String(20), nullable=False, default="WGS84", server_default="WGS84")

    location_origin: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    location_validation_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Section 3A: "do not invent positional accuracy or uncertainty
    # values." This is None unless a source or a documented computation
    # actually supplied one -- app/geo/validation.py never writes a
    # fabricated figure here, and absence is read as "unknown," never
    # as zero uncertainty.
    location_uncertainty_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    altitude_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    altitude_reference: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # A short, human-readable note on where/how this location was
    # obtained or transformed (e.g. "seed script, synthetic_demo" or
    # "converted from UTM zone 43N" once a conversion pipeline exists).
    # Never a place for secrets or free-form PII.
    location_provenance_note: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
