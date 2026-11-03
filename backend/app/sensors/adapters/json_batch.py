"""JSON sensor-observation batch adapter. Same bounded,
in-memory contract as app.connectors.json_connector.JSONFileConnector:
the caller has already size-capped `content` before this adapter ever
sees it."""
from __future__ import annotations

import json
from typing import Optional

from app.connectors.base import BaseConnector
from app.connectors.types import ConnectorError, ConnectorResult, ErrorCategory, RawRecord


class SensorJsonBatchConnector(BaseConnector):
    connector_type = "sensor_json_batch"
    connector_version = "1.0"

    def __init__(self, config: Optional[dict] = None, *, content: bytes = b""):
        super().__init__(config)
        self.content = content

    def validate_config(self) -> list[str]:
        return []

    def fetch(self, *, cursor: Optional[str] = None, limit: int = 500, **kwargs) -> ConnectorResult:
        result = ConnectorResult(connector_type=self.connector_type, connector_version=self.connector_version)
        try:
            data = json.loads(self.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            result.errors.append(ConnectorError(ErrorCategory.UNSUPPORTED_CONTENT, f"invalid JSON: {exc}"))
            return result

        if isinstance(data, dict):
            data = data.get("observations", [data]) if "observations" in data else [data]
        if not isinstance(data, list):
            result.errors.append(ConnectorError(ErrorCategory.UNSUPPORTED_CONTENT, "sensor JSON batch must be an object, {\"observations\": [...]}, or a list of objects"))
            return result

        if len(data) > limit:
            result.errors.append(ConnectorError(ErrorCategory.SIZE_LIMIT, f"batch of {len(data)} records exceeds the {limit}-record limit for this request"))
            data = data[:limit]

        for item in data:
            if not isinstance(item, dict):
                result.errors.append(ConnectorError(ErrorCategory.VALIDATION, f"skipping a non-object list entry: {type(item).__name__}"))
                continue
            result.records.append(RawRecord(
                payload=item,
                external_id=_str_or_none(item.get("external_id")),
                source_observed_at_raw=_str_or_none(item.get("observed_at")),
            ))

        result.has_more = False
        return result


def _str_or_none(value) -> Optional[str]:
    return str(value) if value not in (None, "") else None
