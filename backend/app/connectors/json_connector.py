"""JSON file connector. Reads a bounded in-memory byte string (the
upload is already size-capped by app/core/config.py's MAX_UPLOAD_BYTES
before this connector ever sees it) and yields one RawRecord per
top-level list item, or a single record for a bare JSON object."""
from __future__ import annotations

import json
from typing import Optional

from app.connectors.base import BaseConnector
from app.connectors.types import ConnectorError, ConnectorResult, ErrorCategory, RawRecord


class JSONFileConnector(BaseConnector):
    connector_type = "json_file"
    connector_version = "1.0"

    def __init__(self, config: Optional[dict] = None, *, content: bytes = b""):
        super().__init__(config)
        self.content = content

    def validate_config(self) -> list[str]:
        return []  # a file connector takes no persistent configuration

    def fetch(self, *, cursor: Optional[str] = None, limit: int = 500, **kwargs) -> ConnectorResult:
        result = ConnectorResult(connector_type=self.connector_type, connector_version=self.connector_version)
        try:
            data = json.loads(self.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            result.errors.append(ConnectorError(ErrorCategory.UNSUPPORTED_CONTENT, f"invalid JSON: {exc}"))
            return result

        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            result.errors.append(ConnectorError(ErrorCategory.UNSUPPORTED_CONTENT, "JSON upload must be an object or a list of objects"))
            return result

        for item in data:
            if not isinstance(item, dict):
                result.errors.append(ConnectorError(ErrorCategory.VALIDATION, f"skipping a non-object list entry: {type(item).__name__}"))
                continue
            result.records.append(RawRecord(payload=item, external_id=_str_or_none(item.get("external_id"))))

        result.has_more = False
        return result


def _str_or_none(value) -> Optional[str]:
    return str(value) if value not in (None, "") else None
