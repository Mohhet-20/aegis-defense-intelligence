"""The connector lifecycle contract. Every connector --
file-based today, HTTP/synthetic also today, sensor/CV/edge adapters
in later work -- implements this same small interface. The
ingestion engine (app/services/ingestion_service.py) only ever talks
to a connector through these methods."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.connectors.types import ConnectorResult


class BaseConnector(ABC):
    #: Stable machine name, used as the `connector_type` recorded on
    #: every RawRecord this connector produces.
    connector_type: str = "base"
    #: Bumped whenever this connector's output shape or behavior
    #: changes in a way that matters for provenance/debugging.
    connector_version: str = "1.0"

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}

    @abstractmethod
    def validate_config(self) -> list[str]:
        """Returns a list of human-readable problems with self.config.
        An empty list means the configuration is valid. Never raises
        for an ordinary configuration problem -- that's what the
        return value is for; exceptions are reserved for programmer
        error."""

    def check_connectivity(self) -> tuple[bool, Optional[str]]:
        """Best-effort reachability check. Most connector types (file
        upload, synthetic) have nothing to check and simply return
        (True, None) -- "connectivity" isn't a meaningful concept for
        them. Only override this when there's a real endpoint to
        probe."""
        return True, None

    @abstractmethod
    def fetch(self, *, cursor: Optional[str] = None, limit: int = 500, **kwargs) -> ConnectorResult:
        """Returns up to `limit` records starting after `cursor`. A
        connector that has no real notion of a cursor (a one-shot file
        upload) ignores it and always returns has_more=False."""

    def close(self) -> None:
        """Release any held resources (sockets, file handles). A
        no-op for connectors that don't hold any."""
        return None
