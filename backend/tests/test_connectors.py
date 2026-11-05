"""Connector unit tests. Each connector's
validate_config()/fetch() contract, SSRF defenses, and determinism are
tested directly -- no HTTP client/database involved except for the
local mock server the HTTP connector tests spin up ("test
against a local mock server and document that no real external source
is connected" -- this IS that local mock server, and it never leaves
127.0.0.1).
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.connectors.csv_connector import CSVFileConnector
from app.connectors.json_connector import JSONFileConnector
from app.connectors.synthetic_connector import SyntheticDemoConnector
from app.connectors.types import ConnectorConfigError, ErrorCategory
from app.connectors.url_safety import validate_url


# --- JSON file connector --------------------------------------------------


def test_json_connector_parses_list_of_objects():
    content = b'[{"event_type": "a", "external_id": "1"}, {"event_type": "b", "external_id": "2"}]'
    result = JSONFileConnector(content=content).fetch()
    assert len(result.records) == 2
    assert not result.errors


def test_json_connector_wraps_a_bare_object_in_a_list():
    result = JSONFileConnector(content=b'{"event_type": "a"}').fetch()
    assert len(result.records) == 1


def test_json_connector_skips_non_object_list_entries_as_errors_not_crashes():
    result = JSONFileConnector(content=b'[{"event_type": "a"}, "not an object", 42]').fetch()
    assert len(result.records) == 1
    assert len(result.errors) == 2
    assert all(e.category == ErrorCategory.VALIDATION for e in result.errors)


def test_json_connector_reports_invalid_json_as_a_connector_error_not_an_exception():
    result = JSONFileConnector(content=b"{not valid json").fetch()
    assert not result.records
    assert result.errors[0].category == ErrorCategory.UNSUPPORTED_CONTENT


# --- CSV file connector ---------------------------------------------------


def test_csv_connector_parses_rows():
    content = b"event_type,title,external_id\na,A,1\nb,B,2\n"
    result = CSVFileConnector(content=content).fetch()
    assert len(result.records) == 2
    assert result.records[0].payload["event_type"] == "a"
    assert result.records[0].external_id == "1"


def test_csv_connector_skips_rows_with_extra_columns_as_errors():
    content = b"event_type,title\na,A,extra,columns\nb,B\n"
    result = CSVFileConnector(content=content).fetch()
    assert len(result.records) == 1  # only the well-formed row
    assert len(result.errors) == 1
    assert result.errors[0].category == ErrorCategory.VALIDATION


def test_csv_connector_reports_missing_header_as_a_connector_error():
    result = CSVFileConnector(content=b"").fetch()
    assert not result.records
    assert result.errors[0].category == ErrorCategory.UNSUPPORTED_CONTENT


# --- Synthetic demo connector ----------------------------------------------


def test_synthetic_connector_is_deterministic_for_a_given_seed():
    connector = SyntheticDemoConnector({"count": 10, "seed": 42})
    first = connector.fetch()
    second = connector.fetch()
    assert [r.external_id for r in first.records] == [r.external_id for r in second.records]
    assert [r.payload["event_type"] for r in first.records] == [r.payload["event_type"] for r in second.records]


def test_synthetic_connector_different_seeds_produce_different_batches():
    a = SyntheticDemoConnector({"count": 10, "seed": 1}).fetch()
    b = SyntheticDemoConnector({"count": 10, "seed": 2}).fetch()
    assert [r.external_id for r in a.records] != [r.external_id for r in b.records]


def test_synthetic_connector_records_are_explicitly_labeled_synthetic():
    result = SyntheticDemoConnector({"count": 1, "seed": 0}).fetch()
    assert "synthetic" in result.records[0].payload["description"].lower()


@pytest.mark.parametrize("count", [0, -1, 501, "five"])
def test_synthetic_connector_rejects_out_of_range_count(count):
    errors = SyntheticDemoConnector({"count": count}).validate_config()
    assert errors


# --- URL safety (SSRF defenses) --------------------------------------------


def test_validate_url_requires_https_by_default():
    with pytest.raises(ConnectorConfigError):
        validate_url("http://example.com/feed")


def test_validate_url_blocks_loopback_by_default():
    with pytest.raises(ConnectorConfigError):
        validate_url("http://127.0.0.1:9999/feed")


def test_validate_url_allows_loopback_with_allow_local_dev():
    validate_url("http://127.0.0.1:9999/feed", allow_local_dev=True)  # must not raise


def test_validate_url_blocks_cloud_metadata_even_with_allow_local_dev():
    with pytest.raises(ConnectorConfigError):
        validate_url("http://169.254.169.254/latest/meta-data/", allow_local_dev=True)


def test_validate_url_rejects_embedded_credentials():
    with pytest.raises(ConnectorConfigError):
        validate_url("https://user:password@example.com/feed")


# --- HTTP connector against a local mock server ----------------------------


@pytest.fixture()
def mock_json_server():
    """A plain stdlib HTTP server bound to 127.0.0.1 -- Section 4's
    "test against a local mock server" requirement. This is the only
    network endpoint any test talks to; no real external
    source is ever contacted."""
    payload = {
        "items": [
            {"external_id": "http-1", "event_type": "perimeter_motion", "title": "R1", "observed_at": "2026-01-01T00:00:00Z"},
            {"external_id": "http-2", "event_type": "unidentified_vehicle", "title": "R2", "observed_at": "2026-01-01T01:00:00Z"},
        ],
        "next_cursor": None,
    }
    body = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/events"
    finally:
        server.shutdown()


def test_http_connector_fetches_records_from_local_mock_server(mock_json_server):
    from app.connectors.http_connector import HttpApiConnector

    connector = HttpApiConnector({"url": mock_json_server, "allow_local_dev": True})
    assert connector.validate_config() == []
    ok, detail = connector.check_connectivity()
    assert ok is True
    result = connector.fetch()
    assert len(result.records) == 2
    assert result.records[0].external_id == "http-1"


def test_http_connector_without_allow_local_dev_refuses_loopback(mock_json_server):
    from app.connectors.http_connector import HttpApiConnector

    connector = HttpApiConnector({"url": mock_json_server})
    errors = connector.validate_config()
    assert errors  # loopback is rejected unless explicitly opted into


def test_http_connector_validate_config_requires_a_url():
    from app.connectors.http_connector import HttpApiConnector

    errors = HttpApiConnector({}).validate_config()
    assert any("url" in e for e in errors)


def test_http_connector_validate_config_rejects_bad_timeout():
    from app.connectors.http_connector import HttpApiConnector

    errors = HttpApiConnector({"url": "https://example.com", "timeout_seconds": -1}).validate_config()
    assert any("timeout_seconds" in e for e in errors)


def test_http_connector_validate_config_rejects_a_literal_credential_as_auth_env_var():
    from app.connectors.http_connector import HttpApiConnector

    errors = HttpApiConnector({"url": "https://example.com", "auth_env_var": 12345}).validate_config()
    assert any("auth_env_var" in e for e in errors)


def test_http_connector_auth_header_uses_only_the_named_env_var(monkeypatch):
    from app.connectors.http_connector import HttpApiConnector

    monkeypatch.setenv("TEST_AEGIS_TOKEN", "secret-token-value")
    connector = HttpApiConnector({"url": "https://example.com", "auth_env_var": "TEST_AEGIS_TOKEN"})
    assert connector._auth_headers() == {"Authorization": "Bearer secret-token-value"}

    connector_unset = HttpApiConnector({"url": "https://example.com", "auth_env_var": "TEST_AEGIS_TOKEN_NOT_SET"})
    assert connector_unset._auth_headers() == {}


@pytest.fixture()
def mock_server_factory():
    """Lets a test spin up a mock server with a custom handler
    (non-200 status, wrong content-type, oversized body, a redirect to
    somewhere unsafe) -- still never leaving 127.0.0.1."""
    servers = []

    def _make(handler_cls):
        server = HTTPServer(("127.0.0.1", 0), handler_cls)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return f"http://127.0.0.1:{port}/events"

    yield _make
    for s in servers:
        s.shutdown()


def test_http_connector_reports_non_200_status_as_an_http_error(mock_server_factory):
    from app.connectors.http_connector import HttpApiConnector
    from app.connectors.types import ErrorCategory as EC

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503)
            self.end_headers()

        def log_message(self, *a):
            pass

    url = mock_server_factory(Handler)
    result = HttpApiConnector({"url": url, "allow_local_dev": True}).fetch()
    assert not result.records
    assert result.errors[0].category == EC.HTTP_ERROR


def test_http_connector_rejects_unexpected_content_type(mock_server_factory):
    from app.connectors.http_connector import HttpApiConnector
    from app.connectors.types import ErrorCategory as EC

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<html>not json</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    url = mock_server_factory(Handler)
    result = HttpApiConnector({"url": url, "allow_local_dev": True}).fetch()
    assert not result.records
    assert result.errors[0].category == EC.UNSUPPORTED_CONTENT


def test_http_connector_rejects_oversized_response(mock_server_factory, monkeypatch):
    import app.connectors.http_connector as http_connector_module
    from app.connectors.http_connector import HttpApiConnector
    from app.connectors.types import ErrorCategory as EC

    monkeypatch.setattr(http_connector_module, "MAX_RESPONSE_BYTES", 10)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"items": [{"external_id": str(i)} for i in range(50)]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    url = mock_server_factory(Handler)
    result = HttpApiConnector({"url": url, "allow_local_dev": True}).fetch()
    assert not result.records
    assert result.errors[0].category == EC.SIZE_LIMIT


def test_http_connector_revalidates_a_redirect_to_an_unsafe_destination(mock_server_factory):
    from app.connectors.http_connector import HttpApiConnector
    from app.connectors.types import ErrorCategory as EC

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()

        def log_message(self, *a):
            pass

    url = mock_server_factory(Handler)
    result = HttpApiConnector({"url": url, "allow_local_dev": True}).fetch()
    assert not result.records
    assert result.errors[0].category == EC.UNSAFE_DESTINATION


def test_http_connector_check_connectivity_reports_failure_for_an_unreachable_host():
    from app.connectors.http_connector import HttpApiConnector

    connector = HttpApiConnector({"url": "http://127.0.0.1:1/unreachable", "allow_local_dev": True, "timeout_seconds": 1})
    ok, detail = connector.check_connectivity()
    assert ok is False
    assert detail
