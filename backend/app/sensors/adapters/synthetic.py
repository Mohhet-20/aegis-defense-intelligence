"""Deterministic synthetic sensor-observation connector (Section 2:
"use deterministic synthetic fixtures when sample data is needed").
Every record is labeled data_origin="synthetic_demo" by the ingestion
service (never claimed as a live feed) and is fully reproducible from
(seed, count, base_value, noise_amplitude) -- the same seed always
produces byte-identical output, which is what makes this usable as a
real test fixture for the statistics/anomaly engines, not just a demo."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.connectors.base import BaseConnector
from app.connectors.types import ConnectorError, ConnectorResult, ErrorCategory, RawRecord


class SyntheticSensorConnector(BaseConnector):
    connector_type = "sensor_synthetic"
    connector_version = "1.0"

    def validate_config(self) -> list[str]:
        errors = []
        if not self.config.get("sensor_id"):
            errors.append("config.sensor_id is required")
        if not self.config.get("measurement_type"):
            errors.append("config.measurement_type is required")
        count = self.config.get("count", 20)
        if not isinstance(count, int) or count < 1 or count > 2000:
            errors.append("config.count must be an integer between 1 and 2000")
        return errors

    def fetch(self, *, cursor: Optional[str] = None, limit: int = 2000, **kwargs) -> ConnectorResult:
        result = ConnectorResult(connector_type=self.connector_type, connector_version=self.connector_version)
        config_errors = self.validate_config()
        if config_errors:
            result.errors.append(ConnectorError(ErrorCategory.CONFIGURATION, "; ".join(config_errors)))
            return result

        sensor_id = self.config["sensor_id"]
        measurement_type = self.config["measurement_type"]
        unit = self.config.get("unit")
        count = min(int(self.config.get("count", 20)), limit)
        seed = self.config.get("seed", 0)
        base_value = float(self.config.get("base_value", 20.0))
        noise_amplitude = float(self.config.get("noise_amplitude", 0.5))
        interval_seconds = float(self.config.get("interval_seconds", 60.0))
        # Index -> absolute value override, for deterministically
        # injecting a known outlier/range-violation/repeated-value run
        # at a specific position -- what the test suite uses to build
        # "a known synthetic outlier" fixture without hand-writing one
        # observation at a time.
        overrides: dict[int, float] = {int(k): float(v) for k, v in (self.config.get("value_overrides") or {}).items()}
        skip_indices = set(int(i) for i in (self.config.get("skip_indices") or []))

        rng = random.Random(seed)
        start = self.config.get("start_at")
        start_dt = datetime.fromisoformat(start) if isinstance(start, str) else datetime.now(timezone.utc) - timedelta(seconds=interval_seconds * count)

        for i in range(count):
            if i in skip_indices:
                continue
            value = overrides.get(i, round(base_value + rng.uniform(-noise_amplitude, noise_amplitude), 4))
            observed_at = start_dt + timedelta(seconds=interval_seconds * i)
            payload = {
                "sensor_id": sensor_id,
                "measurement_type": measurement_type,
                "value": value,
                "unit": unit,
                "observed_at": observed_at.isoformat(),
                "external_id": f"synthetic-sensor-{seed}-{sensor_id}-{measurement_type}-{i}",
                "note": "deterministic synthetic demonstration record -- not a real sensor reading",
            }
            result.records.append(RawRecord(payload=payload, external_id=payload["external_id"], source_observed_at_raw=payload["observed_at"]))

        result.has_more = False
        return result
