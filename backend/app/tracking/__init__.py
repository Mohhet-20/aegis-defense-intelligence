"""Object tracking. Associates already-persisted
`DetectionResult` rows across the frames of one video into
sequence-scoped tracks. See docs/architecture/OBJECT_TRACKING_ARCHITECTURE.md.

This package contains no database access and no FastAPI dependency --
every module here is pure, synchronous, deterministic Python operating
on plain dataclasses, so it can be (and is) unit-tested in complete
isolation from the rest of the application. app/services/tracking_service.py
is the only place that wires this package to the database and the API.
"""
