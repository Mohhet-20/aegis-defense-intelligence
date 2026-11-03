"""Deterministic synthetic demonstration connector ("a
synthetic demonstration connector for deterministic local
development"). Every record it produces is run through the same
normalization/validation/dedup pipeline as any real upload, and is
always labeled data_origin="synthetic_demo" by the ingestion service --
this connector never claims to be a live feed."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.connectors.base import BaseConnector
from app.connectors.types import ConnectorResult, RawRecord

_EVENT_TYPES = ["perimeter_motion", "unidentified_vehicle", "access_attempt", "sensor_offline", "anomalous_pattern"]
_SEVERITIES = ["low", "medium", "high"]


class SyntheticDemoConnector(BaseConnector):
    connector_type = "synthetic_demo"
    connector_version = "1.0"

    def validate_config(self) -> list[str]:
        errors = []
        count = self.config.get("count", 5)
        if not isinstance(count, int) or count < 1 or count > 500:
            errors.append("config.count must be an integer between 1 and 500")
        return errors

    def fetch(self, *, cursor: Optional[str] = None, limit: int = 500, **kwargs) -> ConnectorResult:
        result = ConnectorResult(connector_type=self.connector_type, connector_version=self.connector_version)
        count = min(int(self.config.get("count", 5)), limit)
        seed = self.config.get("seed", 0)
        rng = random.Random(seed)  # deterministic -- same seed always produces the same batch
        now = datetime.now(timezone.utc)

        for i in range(count):
            event_type = rng.choice(_EVENT_TYPES)
            offset_minutes = rng.randint(0, 24 * 60)
            payload = {
                "external_id": f"synthetic-{seed}-{i}",
                "event_type": event_type,
                "title": f"Synthetic {event_type.replace('_', ' ')} event #{i}",
                "description": "Deterministic synthetic demonstration record -- not a real observation.",
                "observed_at": (now - timedelta(minutes=offset_minutes)).isoformat(),
                "severity": rng.choice(_SEVERITIES),
                "latitude": round(38.88 + rng.uniform(-0.02, 0.02), 6) if rng.random() > 0.3 else None,
                "longitude": round(-77.03 + rng.uniform(-0.02, 0.02), 6) if rng.random() > 0.3 else None,
            }
            result.records.append(RawRecord(payload=payload, external_id=payload["external_id"]))

        result.has_more = False
        return result
