"""Browser ("cookie mode") sessions: the refresh token lives only in an HttpOnly,
SameSite=Strict cookie scoped to /api/v1/auth; API clients without the header keep
the token-in-body behaviour."""
from __future__ import annotations

from app.core.config import get_settings

API = "/api/v1/auth"
COOKIE_MODE = {"X-Session-Mode": "cookie"}


def _set_cookie_header(response) -> str:
    return "; ".join(v for k, v in response.headers.multi_items() if k.lower() == "set-cookie")


def _login(client, test_password, headers=None):
    return client.post(f"{API}/login", json={"username_or_email": "analyst", "password": test_password}, headers=headers or {})


def test_cookie_mode_login_keeps_the_refresh_token_out_of_javascript(client, seeded_users, test_password):
    r = _login(client, test_password, COOKIE_MODE)
    assert r.status_code == 200
    assert r.json()["refresh_token"] is None and r.json()["access_token"]
    cookie = _set_cookie_header(r).lower()
    assert "aegis_refresh=" in cookie
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/v1/auth" in cookie
    assert "secure" not in cookie  # development default: plain-http localhost


def test_api_clients_without_the_header_are_unchanged(client, seeded_users, test_password):
    r = _login(client, test_password)
    assert r.json()["refresh_token"]
    assert "aegis_refresh" not in _set_cookie_header(r)
    again = client.post(f"{API}/refresh", json={"refresh_token": r.json()["refresh_token"]})
    assert again.status_code == 200 and again.json()["refresh_token"]


def test_cookie_refresh_requires_the_custom_header(client, seeded_users, test_password):
    _login(client, test_password, COOKIE_MODE)  # the TestClient keeps the cookie, like a browser
    assert client.post(f"{API}/refresh").status_code == 401           # cookie alone: refused (CSRF guard)
    ok = client.post(f"{API}/refresh", headers=COOKIE_MODE)
    assert ok.status_code == 200 and ok.json()["access_token"] and ok.json()["refresh_token"] is None
    assert "aegis_refresh=" in _set_cookie_header(ok)                  # cookie re-issued
    me = client.get(f"{API}/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["username"] == "analyst"


def test_revoking_sessions_invalidates_the_cookie(client, seeded_users, test_password):
    access = _login(client, test_password, COOKIE_MODE).json()["access_token"]
    assert client.post(f"{API}/revoke-sessions", headers={"Authorization": f"Bearer {access}"}).status_code == 204
    assert client.post(f"{API}/refresh", headers=COOKIE_MODE).status_code == 401


def test_logout_clears_the_cookie(client, seeded_users, test_password):
    _login(client, test_password, COOKIE_MODE)
    out = client.post(f"{API}/logout")
    assert out.status_code == 204
    cleared = _set_cookie_header(out).lower()
    assert "aegis_refresh=" in cleared and ("max-age=0" in cleared or "expires=" in cleared)
    client.cookies.clear()  # what the browser does on receiving the expired cookie
    assert client.post(f"{API}/refresh", headers=COOKIE_MODE).status_code == 401


def test_cookie_is_secure_in_production(client, seeded_users, test_password, monkeypatch):
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "production")
    r = _login(client, test_password, COOKIE_MODE)
    assert "secure" in _set_cookie_header(r).lower()
    monkeypatch.setattr(get_settings(), "AUTH_COOKIE_SECURE", False)  # explicit override, e.g. TLS terminated elsewhere for testing
    assert "secure" not in _set_cookie_header(_login(client, test_password, COOKIE_MODE)).lower()
