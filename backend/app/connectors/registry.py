"""Maps a source's `source_type` to the connector class that knows how
to validate its configuration and (for connector-driven, non-upload
sources) fetch records from it. Adding a new connector -- a future
sensor feed, a CV pipeline output, an edge-sync adapter -- means
adding one entry here, never touching the ingestion engine itself.
"""
from __future__ import annotations

from typing import Optional

from app.connectors.base import BaseConnector
from app.connectors.csv_connector import CSVFileConnector
from app.connectors.http_connector import HttpApiConnector
from app.connectors.json_connector import JSONFileConnector
from app.connectors.synthetic_connector import SyntheticDemoConnector

# The recommended source-type taxonomy. Not a hard DB
# constraint -- Phase 1 already seeded sources with looser values
# ("manual", "synthetic_generator") and breaking those would violate
# "preserve existing records." New sources should use these names.
RECOMMENDED_SOURCE_TYPES = (
    "manual_upload",
    "json_file",
    "csv_file",
    "http_api",
    "internal_application",
    "synthetic_demo",
    "future_connector",
)

# Only source types with a real, connector-driven fetch() path (i.e.
# NOT a one-shot file upload, which is handled directly by
# ingestion_service using JSONFileConnector/CSVFileConnector against
# the uploaded bytes) are registered for "run this source" / "check
# connectivity" / "validate config" purposes.
_CONNECTOR_CLASSES: dict[str, type[BaseConnector]] = {
    "http_api": HttpApiConnector,
    "synthetic_demo": SyntheticDemoConnector,
    # Legacy Phase-1 seed value, kept working rather than renamed.
    "synthetic_generator": SyntheticDemoConnector,
}

# File-upload connectors, keyed by file extension -- selection has
# always been by the uploaded file's extension, not the source's
# source_type (a single "manual_upload" source can receive either).
_FILE_CONNECTOR_CLASSES: dict[str, type[BaseConnector]] = {
    "json": JSONFileConnector,
    "csv": CSVFileConnector,
}


def get_connector_class(source_type: str) -> Optional[type[BaseConnector]]:
    return _CONNECTOR_CLASSES.get(source_type)


def get_file_connector_class(extension: str) -> Optional[type[BaseConnector]]:
    return _FILE_CONNECTOR_CLASSES.get(extension.lower())


def is_connector_driven(source_type: str) -> bool:
    """True for a source that can be "run" directly (HTTP, synthetic)
    as opposed to one that only ever receives an uploaded file."""
    return source_type in _CONNECTOR_CLASSES
