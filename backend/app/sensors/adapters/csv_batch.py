"""CSV sensor-observation batch adapter. Expects a header
row containing at minimum sensor_id, measurement_type, value,
observed_at -- extra columns (unit, latitude, longitude, device_status,
external_id) pass through verbatim, same as the Event CSV connector."""
from __future__ import annotations

import csv
import io
from typing import Optional

from app.connectors.base import BaseConnector
from app.connectors.types import ConnectorError, ConnectorResult, ErrorCategory, RawRecord


class SensorCsvBatchConnector(BaseConnector):
    connector_type = "sensor_csv_batch"
    connector_version = "1.0"

    def __init__(self, config: Optional[dict] = None, *, content: bytes = b""):
        super().__init__(config)
        self.content = content

    def validate_config(self) -> list[str]:
        return []

    def fetch(self, *, cursor: Optional[str] = None, limit: int = 500, **kwargs) -> ConnectorResult:
        result = ConnectorResult(connector_type=self.connector_type, connector_version=self.connector_version)
        try:
            text = self.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            result.errors.append(ConnectorError(ErrorCategory.UNSUPPORTED_CONTENT, f"CSV must be UTF-8 encoded: {exc}"))
            return result

        try:
            reader = csv.DictReader(io.StringIO(text))
            if reader.fieldnames is None:
                result.errors.append(ConnectorError(ErrorCategory.UNSUPPORTED_CONTENT, "CSV has no header row"))
                return result
            count = 0
            for row in reader:
                if None in row:
                    result.errors.append(ConnectorError(ErrorCategory.VALIDATION, "row has more columns than the header -- skipped"))
                    continue
                if count >= limit:
                    result.errors.append(ConnectorError(ErrorCategory.SIZE_LIMIT, f"CSV has more than the {limit}-row limit for this request -- remaining rows ignored"))
                    break
                payload = dict(row)
                result.records.append(RawRecord(
                    payload=payload,
                    external_id=_str_or_none(payload.get("external_id")),
                    source_observed_at_raw=_str_or_none(payload.get("observed_at")),
                ))
                count += 1
        except csv.Error as exc:
            result.errors.append(ConnectorError(ErrorCategory.UNSUPPORTED_CONTENT, f"malformed CSV: {exc}"))

        result.has_more = False
        return result


def _str_or_none(value) -> Optional[str]:
    return str(value) if value not in (None, "") else None
