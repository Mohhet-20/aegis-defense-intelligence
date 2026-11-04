"""Phase 17: exhaustive route sweeps driven by the live OpenAPI schema (not a hand-picked sample).

* every protected operation rejects an unauthenticated call (401);
* the set of public operations is an explicit allowlist (a newly public route fails this test);
* no operation returns a 5xx for empty/dummy input, for any role;
* a viewer is never allowed to mutate (except an explicit, reviewed allowlist);
* a foreign-organization administrator can never read or modify an org-A record by guessing its id.
"""
from __future__ import annotations

import re
import uuid

import pytest

from app.main import app

PREFIX = "/api/v1"
METHODS = ("get", "post", "put", "patch", "delete")
DUMMY = str(uuid.UUID(int=12345))

# Reviewed: operations that are intentionally reachable without a bearer token.
PUBLIC_OPS = {
    ("GET", "/health/live"), ("GET", "/health/ready"), ("POST", "/auth/login"), ("POST", "/auth/refresh"),
    # Clears only the caller's own refresh cookie; reads and changes no server state, and
    # must work when the access token has already expired.
    ("POST", "/auth/logout"),
    # Tells the sign-in page whether this is a public demo; returns {"enabled": false} and
    # nothing else unless DEMO_MODE is on (tests/test_demo_mode.py).
    ("GET", "/demo"),
    ("POST", "/demo/session"),  # public-demo guest entry; 404 outside DEMO_MODE (tests/test_demo_mode.py)
}
# Reviewed: device-facing routes authenticate with X-Device-Id / X-Device-Api-Key (require_device_auth), never a user JWT.
DEVICE_OPS = {("POST", "/edge/sync/batch"), ("POST", "/edge/sync/health"), ("POST", "/edge/presence/heartbeat")}
# Reviewed: mutating operations a viewer may legitimately perform on their own account/session.
VIEWER_MUTATIONS_OK = {("POST", "/auth/logout"), ("POST", "/auth/change-password"), ("POST", "/auth/revoke-sessions"),
                      # a conversation is the caller's own private chat workspace, created under the copilot READ permission (retrieval is authorization-filtered)
                      ("POST", "/copilot/conversations")}
# Operations excluded from the generic sweep because a dummy call has side effects outside the DB (none today).
SKIP: set[tuple[str, str]] = set()


def operations():
    out = []
    for path, item in app.openapi()["paths"].items():
        for m in METHODS:
            if m in item:
                out.append((m.upper(), path[len(PREFIX):] if path.startswith(PREFIX) else path, item[m]))
    return out


def fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", DUMMY, path)


def call(client, method, path, headers=None):
    kw = {"headers": headers or {}}
    if method in ("POST", "PUT", "PATCH"):
        kw["json"] = {}
    return client.request(method, PREFIX + fill(path), **kw)


def test_public_operations_are_exactly_the_reviewed_allowlist():
    public = {(m, p) for m, p, op in operations() if not op.get("security")}
    assert public == PUBLIC_OPS | DEVICE_OPS, f"unexpected public: {public - PUBLIC_OPS - DEVICE_OPS}; missing: {PUBLIC_OPS | DEVICE_OPS - public}"


def test_every_protected_operation_rejects_unauthenticated_calls(client):
    wrong = []
    for m, p, op in operations():
        if (m, p) in PUBLIC_OPS or (m, p) in SKIP:
            continue
        r = call(client, m, p)  # device routes must also answer 401 when no device credentials are sent
        if r.status_code != 401:
            wrong.append((m, p, r.status_code))
    assert not wrong, wrong


@pytest.mark.parametrize("role", ["admin", "analyst", "investigator", "viewer"])
def test_no_operation_returns_5xx_for_empty_or_dummy_input(client, seeded_users, tokens, auth_header, role):
    h = auth_header(tokens, role)
    bad = []
    for m, p, _ in operations():
        if (m, p) in PUBLIC_OPS or (m, p) in SKIP or (m, p) in DEVICE_OPS or p.endswith("/logout") or p.endswith("/change-password"):
            continue
        r = call(client, m, p, h)
        if r.status_code >= 500:
            bad.append((m, p, r.status_code, r.text[:120]))
    assert not bad, bad


def test_viewer_cannot_mutate_anything_outside_the_reviewed_allowlist(client, seeded_users, tokens, auth_header):
    h = auth_header(tokens, "viewer")
    leaks = []
    for m, p, _ in operations():
        if m == "GET" or (m, p) in PUBLIC_OPS or (m, p) in VIEWER_MUTATIONS_OK:
            continue
        r = call(client, m, p, h)
        if 200 <= r.status_code < 300:
            leaks.append((m, p, r.status_code))
    assert not leaks, leaks


def test_foreign_admin_never_succeeds_on_guessed_ids(client, org, org_b, seeded_users, b_headers):
    """An administrator of org B calling any {id} operation with an id that does not belong to B must get an error, never 2xx."""
    ok = []
    for m, p, _ in operations():
        if "{" not in p or (m, p) in PUBLIC_OPS or p.endswith("/logout"):
            continue
        r = call(client, m, p, b_headers)
        if 200 <= r.status_code < 300:
            ok.append((m, p, r.status_code))
    assert not ok, ok


def test_device_routes_reject_missing_wrong_and_user_credentials(client, seeded_users, tokens, auth_header):
    for m, p in sorted(DEVICE_OPS):
        assert call(client, m, p).status_code == 401
        assert call(client, m, p, {"X-Device-Id": "nope", "X-Device-Api-Key": "wrong"}).status_code == 401
        assert call(client, m, p, auth_header(tokens, "admin")).status_code == 401  # a human admin token is not a device credential
