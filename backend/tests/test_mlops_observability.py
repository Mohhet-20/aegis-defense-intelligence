"""Metrics registry, structured logging/redaction, error
classification, health separation and observability access control."""
from __future__ import annotations

import io
import json
import logging

import pytest

from app.core import errors, logging_config as lc
from app.core.config import get_settings
from app.core.obs_metrics import CATALOG, UNAVAILABLE, MetricsRegistry, estimate_quantile, norm_label, registry, status_class

API = "/api/v1"


# ---- registry ---------------------------------------------------------------------------
def test_registry_rejects_unknown_metrics_and_labels():
    r = MetricsRegistry(max_series=10)
    with pytest.raises(KeyError):
        r.inc("not_a_metric", {})
    with pytest.raises(KeyError):
        r.inc("http_requests_total", {"method": "GET", "route": "/x", "status_class": "2xx", "user_id": "u1"})  # extra high-cardinality label
    with pytest.raises(KeyError):
        r.inc("http_requests_total", {"method": "GET"})
    with pytest.raises(KeyError):
        r.observe("http_requests_total", {"method": "GET", "route": "/x", "status_class": "2xx"}, 1.0)  # counter used as histogram


def test_cardinality_is_capped_and_overflow_is_counted():
    r = MetricsRegistry(max_series=3)
    for i in range(50):
        r.inc("http_requests_total", {"method": "GET", "route": f"/r{i}", "status_class": "2xx"})
    snap = r.snapshot()
    series = snap["http_requests_total"]["series"]
    assert len(series) <= 4 and sum(s["value"] for s in series) == 50  # 3 admitted + 'other'
    assert any(s["labels"]["route"] == "other" for s in series)
    assert snap["metrics_label_overflow_total"]["series"][0]["value"] == 47


def test_label_values_are_normalised_and_methods_allow_listed():
    assert norm_label("a b;c\n<script>") != "a b;c\n<script>" and len(norm_label("x" * 500)) <= 80
    r = MetricsRegistry(max_series=10)
    r.inc("http_requests_total", {"method": "BREW", "route": "/x", "status_class": "2xx"})
    assert r.snapshot()["http_requests_total"]["series"][0]["labels"]["method"] == "OTHER"
    assert status_class(204) == "2xx" and status_class(503) == "5xx"


def test_invalid_values_ignored_histogram_buckets_and_prometheus_text():
    r = MetricsRegistry(max_series=10)
    r.observe("http_request_duration_seconds", {"method": "GET", "route": "/a"}, float("nan"))
    r.observe("http_request_duration_seconds", {"method": "GET", "route": "/a"}, -1)
    assert r.snapshot()["http_request_duration_seconds"]["series"] == []
    for v in (0.001, 0.2, 3.0):
        r.observe("http_request_duration_seconds", {"method": "GET", "route": "/a"}, v)
    s = r.snapshot()["http_request_duration_seconds"]["series"][0]
    assert s["count"] == 3 and s["bucket_counts"][0] == 1 and s["bucket_counts"][-1] == 3
    text = r.to_prometheus()
    assert "# TYPE http_request_duration_seconds histogram" in text and 'le="+Inf"} 3' in text and "http_request_duration_seconds_count" in text
    q = estimate_quantile(CATALOG["http_request_duration_seconds"][3], s["bucket_counts"], s["count"], 0.5)
    assert q is not None and 0 < q <= 3.0


def test_metrics_can_be_disabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "METRICS_ENABLED", False)
    r = MetricsRegistry(max_series=10)
    r.inc("inference_jobs_total", {"outcome": "completed"})
    assert r.snapshot()["inference_jobs_total"]["series"] == []


def test_http_metrics_use_route_templates_not_raw_paths(client, tokens, auth_header):
    registry.reset()
    a = auth_header(tokens, "analyst")
    client.get(f"{API}/mlops/models/some-guid-1234", headers=a)
    client.get(f"{API}/mlops/models/another-guid-9999", headers=a)
    client.get(f"{API}/definitely/not/a/route/with/secret-token-abc")
    routes = {s["labels"]["route"] for s in registry.snapshot()["http_requests_total"]["series"]}
    assert "/api/v1/mlops/models/{model_id}" in routes or any("{" in r for r in routes)
    assert not any("guid" in r or "secret-token" in r for r in routes)
    assert "unmatched" in routes


def test_inference_job_metrics_recorded(client, tokens, auth_header, png_bytes):
    registry.reset()
    a = auth_header(tokens, "analyst")
    mid = client.post(f"{API}/mlops/models", headers=a, json={"name": "d", "version": "1.0.0", "task_type": "object_detection", "adapter_key": "mock_detector_v1", "supported_media_types": ["image"]}).json()["id"]
    media = client.post(f"{API}/media", headers=a, files={"file": ("x.png", png_bytes(), "image/png")}).json()["id"]
    assert client.post(f"{API}/inference/jobs", headers=a, json={"media_asset_id": media, "model_record_id": mid, "job_type": "image_detection"}).status_code in (200, 201)
    snap = registry.snapshot()
    assert any(s["labels"]["outcome"] == "completed" for s in snap["inference_jobs_total"]["series"])
    assert snap["inference_job_duration_seconds"]["series"][0]["count"] == 1


# ---- endpoints -----------------------------------------------------------------------------
def test_metrics_endpoints_require_observability_permission(client, tokens, auth_header):
    for path in ("/observability/metrics", "/observability/metrics/prometheus", "/observability/health"):
        assert client.get(f"{API}{path}").status_code == 401
        assert client.get(f"{API}{path}", headers=auth_header(tokens, "analyst")).status_code == 403
        assert client.get(f"{API}{path}", headers=auth_header(tokens, "viewer")).status_code == 403
        assert client.get(f"{API}{path}", headers=auth_header(tokens, "admin")).status_code == 200
    body = client.get(f"{API}/observability/metrics", headers=auth_header(tokens, "admin")).json()
    assert set(body["unavailable"]) == set(UNAVAILABLE) and "job_queue_depth" in body["unavailable"] and "process" in body["scope"]
    prom = client.get(f"{API}/observability/metrics/prometheus", headers=auth_header(tokens, "admin"))
    assert prom.headers["content-type"].startswith("text/plain") and "# TYPE http_requests_total counter" in prom.text


def test_summary_is_org_scoped_and_restricts_process_metrics(client, tokens, auth_header):
    s = client.get(f"{API}/observability/summary", headers=auth_header(tokens, "analyst"))
    assert s.status_code == 200
    assert s.json()["requests"]["status"] == "restricted"
    full = client.get(f"{API}/observability/summary", headers=auth_header(tokens, "admin")).json()
    assert full["requests"].get("status") != "restricted"
    assert client.get(f"{API}/observability/summary").status_code == 401
    assert client.get(f"{API}/observability/summary?days=99", headers=auth_header(tokens, "admin")).status_code == 422


def test_detailed_health_reports_dependencies_without_leaking_paths(client, tokens, auth_header, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "MLOPS_ARTIFACT_ROOT", str(tmp_path))
    a = auth_header(tokens, "analyst")
    client.post(f"{API}/mlops/models", headers=a, json={"name": "gone", "version": "1.0.0", "task_type": "classification", "artifact_reference": "artifact:missing.bin"})
    body = client.get(f"{API}/observability/health", headers=auth_header(tokens, "admin")).json()
    assert body["dependencies"]["database"] == "ok" and body["job_queue"]["available"] is False and "migrations" in body
    assert body["ml_capability"]["artifacts_unavailable"] == 1
    assert str(tmp_path) not in json.dumps(body)
    assert {"liveness", "readiness", "detail"} == set(body["probe_semantics"])


def test_liveness_and_readiness_remain_public_and_distinct(client, monkeypatch):
    live = client.get(f"{API}/health/live")
    assert live.status_code == 200 and live.json() == {"status": "alive"}
    ready = client.get(f"{API}/health/ready")
    assert ready.status_code == 200 and set(ready.json()["checks"]) >= {"database", "media_storage"}
    from app.api.routes import health as health_route
    monkeypatch.setattr(health_route, "check_database", lambda db: False)
    bad = client.get(f"{API}/health/ready")
    assert bad.status_code == 503 and bad.json()["status"] == "not_ready" and bad.json()["checks"]["database"] == "error"
    assert client.get(f"{API}/health/live").status_code == 200  # liveness unaffected by a dependency failure


# ---- logging ---------------------------------------------------------------------------------
def _logger(fmt):
    stream = io.StringIO()
    h = logging.StreamHandler(stream)
    h.setFormatter(lc.JsonFormatter("test") if fmt == "json" else lc._TextFormatter())
    h.addFilter(lc.RedactingFilter())
    log = logging.getLogger(f"aegis.test.{fmt}")
    log.handlers[:] = [h]
    log.propagate = False
    log.setLevel(logging.DEBUG)
    return log, stream


def test_json_log_lines_have_standard_fields_and_context(client):
    log, stream = _logger("json")
    tok = lc.request_id_var.set("req-123")
    try:
        log.info("operation done", extra={"operation": "mlops.run", "duration_ms": 12, "outcome": "success"})
    finally:
        lc.request_id_var.reset(tok)
    rec = json.loads(stream.getvalue())
    assert {"timestamp", "severity", "subsystem", "environment", "message", "request_id", "operation", "duration_ms", "outcome"} <= set(rec)
    assert rec["request_id"] == "req-123" and rec["severity"] == "INFO" and rec["environment"] == "test"


@pytest.mark.parametrize("fmt", ["json", "text"])
def test_logs_never_contain_secrets(fmt):
    log, stream = _logger(fmt)
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.abcdefghijklmnop"
    log.warning("login with password=hunter2 and Authorization: Bearer abcdefgh12345678 token=%s", jwt,
                extra={"api_key": "sk-live-123", "payload": {"password": "p", "nested": {"secret": "s", "ok": "fine"}}, "note": "Bearer zzzzzzzzzzzz"})
    out = stream.getvalue()
    for secret in ("hunter2", "abcdefgh12345678", jwt, "sk-live-123", "zzzzzzzzzzzz"):
        assert secret not in out, secret
    assert "[REDACTED]" in out


def test_exception_logging_redacts_and_does_not_break_on_bad_args():
    log, stream = _logger("json")
    try:
        raise RuntimeError("db password=hunter2 failed")
    except RuntimeError:
        log.exception("boom")
    log.info("bad %s %s", "only-one")  # malformed call must not raise
    assert "hunter2" not in stream.getvalue() and "RuntimeError" in stream.getvalue()


def test_long_log_fields_are_truncated():
    log, stream = _logger("json")
    log.info("x", extra={"blob": "a" * 5000})
    assert len(stream.getvalue()) < 3000


def test_configure_logging_default_is_text_and_json_is_selectable():
    lc.configure_logging("INFO", "json")
    root = logging.getLogger()
    assert any(isinstance(h.formatter, lc.JsonFormatter) for h in root.handlers)
    lc.configure_logging("INFO", "text")
    assert not any(isinstance(h.formatter, lc.JsonFormatter) for h in root.handlers)
    assert get_settings().LOG_FORMAT == "text"


# ---- error classification ---------------------------------------------------------------------
def test_error_classification_is_stable_and_sanitised():
    cat, msg = errors.classify_exception(FileNotFoundError("/srv/models/secret/w.bin"))
    assert cat == "missing_artifact" and "/srv" not in msg
    assert errors.classify_exception(PermissionError("x"))[0] == "authorization"
    assert errors.classify_exception(TimeoutError("t"))[0] == "resource_limit"
    assert errors.classify_exception(errors.ResourceLimitExceeded("too big"))[0] == "resource_limit"
    assert errors.classify_exception(errors.MlopsValidationError("bad"))[0] == "validation"
    from sqlalchemy.exc import OperationalError
    cat, msg = errors.classify_exception(OperationalError("SELECT secret FROM t", {}, Exception("conn host=10.0.0.5 password=pw")))
    assert "10.0.0.5" not in msg and "SELECT" not in msg and cat
    cat, msg = errors.classify_exception(ValueError("weird"))
    assert cat == "validation" and "weird" not in msg
    scrubbed = errors.scrub("failed at /home/user/app/x.py password=pw")
    assert "/home/user" not in scrubbed and "=pw" not in scrubbed and "[REDACTED]" in scrubbed
    assert len(errors.scrub("x" * 5000)) <= errors.MAX_MESSAGE


def test_unhandled_exception_returns_sanitised_500_with_request_id(client, monkeypatch):
    from starlette.testclient import TestClient

    from app.api.routes import health as health_route
    client = TestClient(client.app, raise_server_exceptions=False)

    def boom(db):
        raise RuntimeError("password=hunter2 at /srv/x")

    monkeypatch.setattr(health_route, "check_database", boom)
    r = client.get(f"{API}/health/ready")
    assert r.status_code == 500 and "hunter2" not in r.text and "/srv" not in r.text
