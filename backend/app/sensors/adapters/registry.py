"""Closed allow-list mapping a sensor batch's declared format to the
adapter class that parses it -- same discipline as
app.connectors.registry (never a dynamic import of an arbitrary
string). Deliberately a SEPARATE registry from the Event-ingestion one:
sensor observation batches and Event batches are different record
shapes even when both arrive as JSON or CSV.

No HTTP sensor connector is registered here ("do not add
unrestricted network access or arbitrary remote URL fetching" -- this
layer adds no new network egress; a future HTTP sensor source can
reuse app.connectors.http_connector.HttpApiConnector's existing
SSRF-hardened fetch path, but wiring one up is deferred, see
docs/architecture/SENSOR_DATA_ARCHITECTURE.md)."""
from __future__ import annotations

from typing import Optional

from app.connectors.base import BaseConnector
from app.sensors.adapters.csv_batch import SensorCsvBatchConnector
from app.sensors.adapters.json_batch import SensorJsonBatchConnector
from app.sensors.adapters.synthetic import SyntheticSensorConnector

SENSOR_BATCH_FORMATS = ("json", "csv")

_FILE_ADAPTERS: dict[str, type[BaseConnector]] = {
    "json": SensorJsonBatchConnector,
    "csv": SensorCsvBatchConnector,
}

_CONNECTOR_ADAPTERS: dict[str, type[BaseConnector]] = {
    "sensor_synthetic": SyntheticSensorConnector,
}


def get_file_adapter_class(fmt: str) -> Optional[type[BaseConnector]]:
    return _FILE_ADAPTERS.get(fmt.lower())


def get_connector_adapter_class(adapter_key: str) -> Optional[type[BaseConnector]]:
    return _CONNECTOR_ADAPTERS.get(adapter_key)
