"""Phase 17 Phase 6: error responses are consistent and sanitized."""
from __future__ import annotations

import json
import math

API = "/api/v1"
SECRET = "Sup3r-Secret-Value-Do-Not-Echo"


def test_validation_errors_never_echo_the_submitted_values(client, tokens, auth_header):
    # Regression: the 422 body used to include `input` -- the rejected value or
    # the whole request body -- so a mistyped login could reflect a password.
    r = client.post(f"{API}/auth/login", json={"username_or_email": "someone", "pasword": SECRET})
    assert r.status_code == 422
    assert SECRET not in r.text and "input" not in json.dumps(r.json()["detail"])

    r = client.post(f"{API}/auth/login", json={"username_or_email": "x", "password": [SECRET]})
    assert r.status_code == 422 and SECRET not in r.text

    r = client.post(f"{API}/investigations", headers=auth_header(tokens, "analyst"), json={"title": "t", "priority": SECRET})
    assert r.status_code == 422 and SECRET not in r.text


def test_validation_error_shape_is_stable_and_carries_request_id(client):
    r = client.post(f"{API}/auth/login", json={})
    body = r.json()
    assert r.status_code == 422 and isinstance(body["detail"], list) and body["request_id"]
    assert all(set(e) == {"type", "loc", "msg"} for e in body["detail"])


def test_nan_in_a_body_is_a_422_not_a_500(client, tokens, auth_header):
    raw = '{"title": "t", "priority": NaN}'
    r = client.post(f"{API}/investigations", headers={**auth_header(tokens, "analyst"), "Content-Type": "application/json"}, content=raw)
    assert r.status_code == 422


def test_common_error_statuses_share_a_detail_and_request_id(client, tokens, auth_header):
    cases = [
        client.get(f"{API}/events"),                                                      # 401
        client.post(f"{API}/sources", json={"name": "x", "source_type": "manual"}, headers=auth_header(tokens, "viewer")),  # 403
        client.get(f"{API}/events/does-not-exist", headers=auth_header(tokens, "analyst")),  # 404
    ]
    assert [c.status_code for c in cases] == [401, 403, 404]
    for c in cases:
        body = c.json()
        assert isinstance(body["detail"], str) and body["detail"]
        assert body["request_id"] and "Traceback" not in c.text and "sqlalchemy" not in c.text.lower()


def test_unhandled_exception_is_sanitized():
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app() if callable(create_app) else create_app

    def boom():
        raise RuntimeError(f"db password={SECRET} at /srv/internal/path")

    app.add_api_route("/api/v1/_test_boom", boom, methods=["GET"])
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/v1/_test_boom")
    assert r.status_code == 500
    assert SECRET not in r.text and "/srv/internal" not in r.text
    assert r.json()["detail"] == "An internal error occurred." and r.json()["request_id"]
