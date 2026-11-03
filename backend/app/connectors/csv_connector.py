"""CSV file connector. Same size/bounds contract as the JSON
connector -- the upload is already capped before this runs."""
from __future__ import annotations

import csv
import io
from typing import Optional

from app.connectors.base import BaseConnector
from app.connectors.types import ConnectorError, ConnectorResult, ErrorCategory, RawRecord


class CSVFileConnector(BaseConnector):
    connector_type = "csv_file"
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
            for row in reader:
                # DictReader puts any extra, un-headered columns under
                # the None key as a list -- that's malformed input, not
                # a record we silently half-accept.
                if None in row:
                    result.errors.append(ConnectorError(ErrorCategory.VALIDATION, "row has more columns than the header -- skipped"))
                    continue
                payload = dict(row)
                result.records.append(RawRecord(payload=payload, external_id=_str_or_none(payload.get("external_id"))))
        except csv.Error as exc:
            result.errors.append(ConnectorError(ErrorCategory.UNSUPPORTED_CONTENT, f"malformed CSV: {exc}"))

        result.has_more = False
        return result


def _str_or_none(value) -> Optional[str]:
    return str(value) if value not in (None, "") else None
