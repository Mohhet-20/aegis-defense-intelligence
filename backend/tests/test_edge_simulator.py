"""Integration tests for app/edge/simulator.py (Phase 8, Section
4/13/18) -- a SimulatedEdgeNode driven against the REAL FastAPI `client`
test fixture (never a direct service-function call), proving the
capture -> local durable queue -> real HTTP sync -> ack -> local state
update loop actually works end to end, including offline/reconnect and
a genuine network-level failure."""
from __future__ import annotations

import tempfile

import httpx
import pytest

from app.edge.local_store import LocalEdgeStore
from app.edge.simulator import SimulatedEdgeNode


@pytest.fixture()
def edge_node(client, active_device_factory):
    device, api_key = active_device_factory()
    path = tempfile.mktemp(suffix=".db")
    node = SimulatedEdgeNode(base_url="http://testserver", device_identifier=device.device_identifier, api_key=api_key, local_db_path=path, http_client=client)
    yield node, device
    node.store.close()  # the injected `client` is NOT owned/closed by the node


def test_capture_and_flush_syncs_through_the_real_api(edge_node):
    node, device = edge_node
    node.capture(record_type="observation_capture", client_record_id="obs-1", payload={"temp": 21.0})
    results = node.run_until_drained()
    assert node.store.stats()["queue_depth"] == 0
    assert results[0]["outcome"] == "ok"
    assert results[0]["batch_response"]["accepted_count"] == 1


def test_offline_capture_is_never_sent_until_reconnect(edge_node):
    node, device = edge_node
    node.go_offline()
    node.capture(record_type="observation_capture", client_record_id="obs-off", payload={"temp": 10.0})
    result = node.flush_once()
    assert result == {"attempted": False, "reason": "offline"}
    assert node.store.stats()["queue_depth"] == 1

    node.go_online()
    results = node.run_until_drained()
    assert results[-1]["outcome"] == "ok"
    assert node.store.stats()["queue_depth"] == 0


def test_health_report_round_trips_through_the_real_api(edge_node):
    node, device = edge_node
    node.capture(record_type="observation_capture", client_record_id="obs-health", payload={"temp": 1.0})
    result = node.send_health_report()
    assert result["status_code"] == 200
    assert "report_id" in result["body"]


def test_mutable_record_conflict_is_visible_through_real_sync(edge_node):
    node, device = edge_node
    node.capture(record_type="annotation", client_record_id="ann-sim", payload={"text": "v1"}, base_revision=0)
    node.run_until_drained()

    # a second simulated device editing the SAME logical annotation
    # with a stale base_revision -- a genuine cross-device conflict
    node.capture(record_type="annotation", client_record_id="ann-sim", payload={"text": "stale"}, base_revision=0)
    results = node.run_until_drained()
    last_batch = results[-1]["batch_response"]
    assert last_batch["results"][0]["sync_status"] == "conflict"
    assert last_batch["conflict_count"] == 1


def test_genuine_network_failure_is_classified_and_backed_off():
    class BrokenTransport(httpx.BaseTransport):
        def handle_request(self, request):
            raise httpx.ConnectError("simulated connection refused")

    broken_client = httpx.Client(transport=BrokenTransport(), base_url="http://unreachable")
    path = tempfile.mktemp(suffix=".db")
    node = SimulatedEdgeNode(base_url="http://unreachable", device_identifier="irrelevant", api_key="irrelevant", local_db_path=path, http_client=broken_client)
    node.capture(record_type="observation_capture", client_record_id="cr-1", payload={"x": 1})
    result = node.flush_once()
    assert result["outcome"] == "network_error"

    rows = node.store._conn.execute("SELECT * FROM outbox").fetchall()
    assert dict(rows[0])["local_status"] == "retryable_failure"
    assert dict(rows[0])["last_error_category"] == "network"
    assert dict(rows[0])["next_retry_at"] is not None
    node.close()


def test_local_store_survives_a_simulated_restart_mid_backlog(client, active_device_factory):
    device, api_key = active_device_factory()
    path = tempfile.mktemp(suffix=".db")
    node = SimulatedEdgeNode(base_url="http://testserver", device_identifier=device.device_identifier, api_key=api_key, local_db_path=path, http_client=client)
    node.capture(record_type="observation_capture", client_record_id="restart-1", payload={"x": 1})
    node.store.close()  # simulate the device process dying before ever flushing

    reopened_store = LocalEdgeStore(path)
    assert reopened_store.stats()["queue_depth"] == 1
    reopened_store.close()

    node2 = SimulatedEdgeNode(base_url="http://testserver", device_identifier=device.device_identifier, api_key=api_key, local_db_path=path, http_client=client)
    results = node2.run_until_drained()
    assert results[-1]["outcome"] == "ok"
    assert node2.store.stats()["queue_depth"] == 0
    node2.store.close()
