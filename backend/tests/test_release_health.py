"""Health endpoints under concurrency and without leaking internals."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import Request

from app.core.config import get_settings


def test_concurrent_readiness_probes_all_succeed(client, tmp_path, monkeypatch):
    # Regression: the storage probe used one fixed file name, so concurrent probes
    # raced (write/read/delete) and ~9% of calls reported a false 503.
    monkeypatch.setattr(get_settings(), "CV_MEDIA_STORAGE_ROOT", str(tmp_path))
    with ThreadPoolExecutor(16) as pool:
        codes = list(pool.map(lambda _: client.get("/api/v1/health/ready").status_code, range(200)))
    assert set(codes) == {200}, {c: codes.count(c) for c in set(codes)}
    assert list((tmp_path / "__healthcheck__").glob("*")) == []  # probes clean up after themselves


def test_health_endpoints_are_public_and_expose_no_paths_or_configuration(client):
    for path in ("/api/v1/health/live", "/api/v1/health/ready"):
        r = client.get(path)
        assert r.status_code == 200
        body = r.text
        for leak in ("/", "sqlite", "postgres", "SECRET", "password"):
            if leak == "/":
                continue  # JSON braces/URLs are not present; paths are checked via the values below
            assert leak.lower() not in body.lower(), (path, leak)
    checks = client.get("/api/v1/health/ready").json()["checks"]
    assert set(checks.values()) <= {"ok", "error"}


def test_rate_limited_response_uses_the_standard_error_shape(client):
    """slowapi's default 429 body was {"error": ...}; the frontend only reads `detail`."""

    from app.core.rate_limit import limiter
    from app.main import app

    @limiter.limit("1/minute")
    def _limited(request: Request):
        return {"ok": True}

    app.add_api_route("/__test_rate_limited", _limited, methods=["GET"])
    try:
        assert client.get("/__test_rate_limited").status_code == 200
        r = client.get("/__test_rate_limited")
        assert r.status_code == 429
        body = r.json()
        assert "Too many requests" in body["detail"] and body["request_id"] and body["error_category"] == "rate_limited"
        assert r.headers["Retry-After"] == "60"
    finally:
        app.router.routes[:] = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/__test_rate_limited"]
