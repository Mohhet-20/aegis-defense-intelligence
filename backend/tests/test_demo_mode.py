"""Public-demo hosting: DEMO_MODE account protection, the /demo endpoint, the
proxy-aware rate-limit key and serving the built frontend from the API process."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.config import get_settings
from app.core.rate_limit import client_address
from app.middleware.hardening import SecurityHeadersMiddleware
from app.web_frontend import DEFAULT_CSP, mount_frontend

API = "/api/v1"


@pytest.fixture()
def demo_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "DEMO_MODE", True)
    monkeypatch.setattr(get_settings(), "DEMO_RESET_HOURS", 6)


# --- /demo -------------------------------------------------------------------

def test_demo_endpoint_reveals_nothing_outside_demo_mode(client):
    assert client.get(f"{API}/demo").json() == {"enabled": False}


def test_demo_endpoint_lists_shared_accounts_in_demo_mode(client, demo_mode):
    body = client.get(f"{API}/demo").json()
    assert body["enabled"] is True and body["reset_hours"] == 6
    assert {a["username"] for a in body["accounts"]} == {"admin", "analyst", "investigator", "viewer"}
    assert body["password"]


# --- account protection ----------------------------------------------------------

def test_demo_accounts_cannot_be_changed_by_visitors(client, tokens, auth_header, seeded_users, demo_mode, test_password):
    admin = auth_header(tokens, "admin")
    target = seeded_users["viewer"].id
    assert client.patch(f"{API}/users/{target}", json={"role": "administrator"}, headers=admin).status_code == 403
    assert client.patch(f"{API}/users/{target}", json={"is_active": False}, headers=admin).status_code == 403
    assert client.post(f"{API}/users/{target}/reset-password", json={"new_password": "Another-Pass-123!"},  # pragma: allowlist secret
                       headers=admin).status_code == 403
    assert client.post(f"{API}/users/{target}/revoke-sessions", headers=admin).status_code == 403
    assert client.post(f"{API}/auth/change-password", json={"current_password": test_password,
                                                            "new_password": "Another-Pass-123!"}, headers=admin).status_code == 403  # pragma: allowlist secret
    assert client.post(f"{API}/auth/revoke-sessions", headers=admin).status_code == 403
    # every account still signs in with the shared password
    for name in ("admin", "viewer"):
        assert client.post(f"{API}/auth/login", json={"username_or_email": name, "password": test_password}).status_code == 200


def test_new_users_remain_fully_manageable_in_demo_mode(client, tokens, auth_header, demo_mode):
    admin = auth_header(tokens, "admin")
    created = client.post(f"{API}/users", json={"username": "visitor1", "email": "visitor1@test.example.com",
                                                "display_name": "Visitor", "password": "Visitor-Pass-123!",  # pragma: allowlist secret
                                                "role": "viewer"}, headers=admin)
    assert created.status_code == 201, created.text
    assert client.patch(f"{API}/users/{created.json()['id']}", json={"role": "analyst"}, headers=admin).status_code == 200


def test_demo_accounts_are_never_locked_out(client, seeded_users, demo_mode, test_password):
    for _ in range(get_settings().MAX_FAILED_LOGIN_ATTEMPTS + 2):
        assert client.post(f"{API}/auth/login", json={"username_or_email": "admin", "password": "wrong"}).status_code == 401  # pragma: allowlist secret
    assert client.post(f"{API}/auth/login", json={"username_or_email": "admin", "password": test_password}).status_code == 200


def test_lockout_still_applies_without_demo_mode(client, seeded_users, test_password):
    for _ in range(get_settings().MAX_FAILED_LOGIN_ATTEMPTS):
        client.post(f"{API}/auth/login", json={"username_or_email": "admin", "password": "wrong"})  # pragma: allowlist secret
    assert client.post(f"{API}/auth/login", json={"username_or_email": "admin", "password": test_password}).status_code == 401


# --- rate-limit key ----------------------------------------------------------------

def _request(peer: str, *xff: str) -> Request:
    headers = [(b"x-forwarded-for", v.encode()) for v in xff]
    return Request({"type": "http", "headers": headers, "client": (peer, 1234), "method": "GET", "path": "/"})


def test_rate_limit_key_ignores_forwarded_headers_by_default(monkeypatch):
    monkeypatch.setattr(get_settings(), "TRUST_FORWARDED_HEADERS", False)
    assert client_address(_request("10.0.0.1", "203.0.113.9")) == "10.0.0.1"


def test_rate_limit_key_uses_the_entry_added_by_the_trusted_proxy(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "TRUST_FORWARDED_HEADERS", True)
    monkeypatch.setattr(s, "TRUSTED_PROXY_HOPS", 1)
    # a client-forged left-hand entry is ignored; the proxy appended the real address
    assert client_address(_request("10.0.0.1", "1.2.3.4, 203.0.113.9")) == "203.0.113.9"
    monkeypatch.setattr(s, "TRUSTED_PROXY_HOPS", 2)
    assert client_address(_request("10.0.0.1", "1.2.3.4, 203.0.113.9", "10.0.0.7")) == "203.0.113.9"
    monkeypatch.setattr(s, "TRUSTED_PROXY_HOPS", 9)   # more hops than entries: the leftmost
    assert client_address(_request("10.0.0.1", "203.0.113.9")) == "203.0.113.9"
    assert client_address(_request("10.0.0.1")) == "10.0.0.1"   # no header: the socket peer


# --- frontend served by the API process ------------------------------------------------

@pytest.fixture()
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (tmp_path / "assets" / "app-1234.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / ".secret").write_text("x", encoding="utf-8")
    (tmp_path.parent / "outside.txt").write_text("outside", encoding="utf-8")
    return tmp_path


def _frontend_client(dist, **kw) -> TestClient:
    app = FastAPI()

    @app.get("/api/v1/ping")
    def ping():
        return {"ok": True}

    mount_frontend(app, str(dist), **kw)
    app.add_middleware(SecurityHeadersMiddleware)
    return TestClient(app)


def test_frontend_spa_fallback_assets_and_api_precedence(dist):
    c = _frontend_client(dist)
    page = c.get("/investigations/abc")
    assert page.status_code == 200 and "id=root" in page.text
    assert page.headers["content-security-policy"] == DEFAULT_CSP
    assert page.headers["cache-control"] == "no-cache" and page.headers["x-frame-options"] == "DENY"
    asset = c.get("/assets/app-1234.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert c.get("/assets/missing.js").status_code == 404        # no HTML for a missing asset
    assert c.get("/favicon.svg").text == "<svg/>"
    assert c.get("/api/v1/ping").json() == {"ok": True}
    assert c.get("/api/v1/nope").status_code == 404 and "id=root" not in c.get("/api/v1/nope").text


def test_frontend_never_serves_hidden_or_outside_files(dist):
    c = _frontend_client(dist)
    assert "id=root" in c.get("/.secret").text                 # falls back to the app, not the file
    assert "outside" not in c.get("/../outside.txt").text
    assert "outside" not in c.get("/%2e%2e/outside.txt").text


def test_frontend_csp_file_and_frame_ancestors(dist, tmp_path_factory):
    csp_file = tmp_path_factory.mktemp("csp") / "csp.txt"
    csp_file.write_text("default-src 'self';\n img-src 'self' https://tile.example.org; frame-ancestors 'none'", encoding="utf-8")
    c = _frontend_client(dist, csp_file=str(csp_file), frame_ancestors="https://huggingface.co")
    page = c.get("/")
    assert page.headers["content-security-policy"] == (
        "default-src 'self'; img-src 'self' https://tile.example.org; frame-ancestors https://huggingface.co")
    assert "x-frame-options" not in page.headers                 # the CSP decides who may frame it
    assert _frontend_client(dist).get("/").headers["x-frame-options"] == "DENY"


def test_mount_frontend_requires_a_built_index(tmp_path):
    with pytest.raises(RuntimeError):
        mount_frontend(FastAPI(), str(tmp_path))
