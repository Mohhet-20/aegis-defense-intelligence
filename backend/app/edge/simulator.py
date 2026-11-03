"""A deterministic, in-process simulated edge device (Phase 8, Section
4/13/18): `SimulatedEdgeNode` captures records into its own
`LocalEdgeStore`, then genuinely sends them over HTTP (via `httpx`) to
whatever `base_url` it's given -- the real FastAPI application, either
a live running server or, in tests, an in-process ASGI transport
(`httpx.Client(transport=httpx.ASGITransport(app=app), ...)`). It is
never wired to the service layer directly -- the whole point is to
exercise the actual device-authenticated HTTP endpoints exactly as a
physical device would.

Honestly stated (see app/edge/__init__.py and the Phase 8 final
report): this has only ever been run against this simulated transport,
never against real edge hardware or a real network.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.edge.local_store import LocalEdgeStore
from app.schemas.edge_sync import EDGE_SYNC_PROTOCOL_VERSION


class SimulatedEdgeNode:
    def __init__(
        self, *, base_url: str, device_identifier: str, api_key: str, local_db_path: str,
        protocol_version: str = EDGE_SYNC_PROTOCOL_VERSION, http_client: Optional[httpx.Client] = None,
    ):
        self.device_identifier = device_identifier
        self.api_key = api_key
        self.protocol_version = protocol_version
        self.store = LocalEdgeStore(local_db_path)
        # A caller may inject its own httpx.Client (e.g. one built with
        # httpx.ASGITransport against the real FastAPI `app` object for
        # tests) -- this class never knows or cares whether it's talking
        # to a live socket or an in-process ASGI transport; either way
        # it's a real HTTP request/response cycle through the real
        # route layer, never a direct service-function call.
        self._client = http_client or httpx.Client(base_url=base_url, timeout=10.0)
        self._owns_client = http_client is None
        self._online = True

    def close(self) -> None:
        self.store.close()
        if self._owns_client:
            self._client.close()

    def go_offline(self) -> None:
        """Models genuine lost connectivity -- while offline, no network
        call is even attempted (not a faked exception), exactly like a
        device with no signal."""
        self._online = False

    def go_online(self) -> None:
        self._online = True

    def is_online(self) -> bool:
        return self._online

    def capture(self, *, record_type: str, client_record_id: str, payload: dict, base_revision: Optional[int] = None, schema_version: str = "v1") -> dict:
        """Local AI inference / sensor capture producing one logical
        record -- durably enqueued immediately,
        regardless of current connectivity."""
        return self.store.enqueue(record_type=record_type, client_record_id=client_record_id, schema_version=schema_version, payload=payload, base_revision=base_revision)

    def _headers(self) -> dict:
        return {"X-Device-Id": self.device_identifier, "X-Device-Api-Key": self.api_key}

    def flush_once(self, *, batch_size: int = 20) -> dict:
        """One send attempt over real HTTP. Never attempted while
        offline. Classifies the response exactly as a real device
        would: a connection-level failure or 5xx is retried with
        locally-computed backoff; a 429 respects the server's
        Retry-After header (Section 7, binding); a 401/403 is never
        retried (the credential itself is the problem)."""
        if not self._online:
            return {"attempted": False, "reason": "offline"}

        pending = self.store.list_ready_to_send(limit=batch_size)
        if not pending:
            return {"attempted": False, "reason": "nothing_pending"}

        row_by_idem = {}
        envelopes = []
        for row in pending:
            fresh = self.store.mark_syncing(row["id"])
            row_by_idem[fresh["idempotency_key"]] = fresh
            envelopes.append(
                {
                    "message_id": fresh["message_id"],
                    "idempotency_key": fresh["idempotency_key"],
                    "record_type": fresh["record_type"],
                    "client_record_id": fresh["client_record_id"],
                    "schema_version": fresh["schema_version"],
                    "payload": json.loads(fresh["payload"]),
                    "payload_hash": fresh["payload_hash"],
                    "source_created_at": fresh["source_created_at"],
                    "queued_at": fresh["queued_at"],
                    "base_revision": fresh["base_revision"],
                }
            )

        batch_payload = {
            "protocol_version": self.protocol_version,
            "device_id": self.device_identifier,
            "batch_id": str(uuid.uuid4()),
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "records": envelopes,
        }

        try:
            response = self._client.post("/api/v1/edge/sync/batch", json=batch_payload, headers=self._headers())
        except httpx.RequestError as exc:
            for row in pending:
                self.store.mark_network_failure(row["id"], message=f"{type(exc).__name__}: {exc}")
            return {"attempted": True, "outcome": "network_error", "sent": len(pending)}

        if response.status_code in (401, 403):
            for row in pending:
                self.store.mark_auth_failure(row["id"], message=f"HTTP {response.status_code}")
            return {"attempted": True, "outcome": "auth_failure", "sent": len(pending)}

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 30))
            for row in pending:
                self.store.apply_ack(row["id"], sync_status="retryable_failure", error_category="rate_limited", error_message="HTTP 429", retry_after_seconds=retry_after)
            return {"attempted": True, "outcome": "rate_limited", "retry_after_seconds": retry_after, "sent": len(pending)}

        if response.status_code >= 500:
            for row in pending:
                self.store.mark_network_failure(row["id"], message=f"HTTP {response.status_code}")
            return {"attempted": True, "outcome": "server_error", "sent": len(pending)}

        if response.status_code != 200:
            for row in pending:
                self.store.apply_ack(row["id"], sync_status="permanent_failure", error_category="validation_error", error_message=f"HTTP {response.status_code}: {response.text[:200]}")
            return {"attempted": True, "outcome": "unexpected_status", "status_code": response.status_code, "sent": len(pending)}

        body = response.json()
        for result in body["results"]:
            row = row_by_idem.get(result["idempotency_key"])
            if row is None:
                continue
            self.store.apply_ack(
                row["id"], sync_status=result["sync_status"], sync_record_id=result.get("sync_record_id"),
                error_category=result.get("error_category"), error_message=result.get("error_message"),
                retry_after_seconds=result.get("retry_after_seconds"),
            )
        return {"attempted": True, "outcome": "ok", "sent": len(pending), "batch_response": body}

    def run_until_drained(self, *, max_cycles: int = 20, batch_size: int = 20) -> list[dict]:
        """Repeatedly flushes until the local outbox has nothing left
        ready to send, or `max_cycles` is hit (never an unbounded
        loop)."""
        results = []
        for _ in range(max_cycles):
            if self.store.stats()["queue_depth"] == 0:
                break
            result = self.flush_once(batch_size=batch_size)
            results.append(result)
            if not result.get("attempted"):
                break
        return results

    def send_health_report(self) -> dict:
        stats = self.store.stats()
        payload = {
            "protocol_version": self.protocol_version,
            "reported_at": datetime.now(timezone.utc).isoformat(),
            "connectivity_state": "online" if self._online else "offline",
            "queue_depth": stats["queue_depth"],
            "pending_sync_count": stats["pending_sync_count"],
        }
        if not self._online:
            return {"attempted": False, "reason": "offline"}
        response = self._client.post("/api/v1/edge/sync/health", json=payload, headers=self._headers())
        return {"attempted": True, "status_code": response.status_code, "body": response.json() if response.status_code == 200 else response.text}
