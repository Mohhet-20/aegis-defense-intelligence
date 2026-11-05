"""Authentication, session revocation, password policy,
account-administration safety, and route-level authorization coverage."""
from __future__ import annotations

import logging

import pytest
import jwt

from app.core.config import get_settings
from app.core.security import create_access_token, decode_token
from app.models.audit import AuditRecord
from app.models.user import User

API = "/api/v1"
STRONG = "Str0ngPassphrase-42"


def _login(client, username, password):
    return client.post(f"{API}/auth/login", json={"username_or_email": username, "password": password})


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ---- password policy -------------------------------------------------------

@pytest.mark.parametrize("pw,fragment", [
    ("short1A", "at least"),
    ("onlylettersnodigits", "digit"),
    ("12345678901234", "letter"),
    ("Password123", "too common"),
])
def test_create_user_enforces_password_policy(client, seeded_users, tokens, auth_header, pw, fragment):
    r = client.post(f"{API}/users", headers=auth_header(tokens, "admin"), json={
        "username": "newuser", "email": "newuser@test.example.com", "display_name": "N", "password": pw, "role": "viewer"})
    assert r.status_code == 422, r.text
    assert fragment in r.json()["detail"]


def test_password_must_not_contain_username(client, seeded_users, tokens, auth_header):
    r = client.post(f"{API}/users", headers=auth_header(tokens, "admin"), json={
        "username": "carolsmith", "email": "c@test.example.com", "display_name": "C", "password": "carolsmith-9999", "role": "viewer"})
    assert r.status_code == 422 and "username" in r.json()["detail"]


def test_create_user_with_strong_password_succeeds_and_audit_has_no_password(client, db, seeded_users, tokens, auth_header):
    r = client.post(f"{API}/users", headers=auth_header(tokens, "admin"), json={
        "username": "dana", "email": "dana@test.example.com", "display_name": "D", "password": STRONG, "role": "viewer"})
    assert r.status_code == 201, r.text
    rows = db.query(AuditRecord).filter(AuditRecord.action == "user.create").all()
    assert rows and STRONG not in str([x.context_metadata for x in rows])


# ---- change password / revocation ---------------------------------------------

def test_change_password_revokes_all_existing_tokens(client, seeded_users, test_password):
    t = _login(client, "viewer", test_password).json()
    old_access, old_refresh = t["access_token"], t["refresh_token"]
    assert client.get(f"{API}/auth/me", headers=_bearer(old_access)).status_code == 200

    r = client.post(f"{API}/auth/change-password", headers=_bearer(old_access),
                    json={"current_password": test_password, "new_password": STRONG})
    assert r.status_code == 200, r.text
    new = r.json()

    assert client.get(f"{API}/auth/me", headers=_bearer(old_access)).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401
    assert client.get(f"{API}/auth/me", headers=_bearer(new["access_token"])).status_code == 200
    assert _login(client, "viewer", test_password).status_code == 401
    assert _login(client, "viewer", STRONG).status_code == 200


def test_change_password_wrong_current_is_rejected_and_audited(client, db, seeded_users, test_password):
    t = _login(client, "viewer", test_password).json()
    r = client.post(f"{API}/auth/change-password", headers=_bearer(t["access_token"]),
                    json={"current_password": "not-the-password-1", "new_password": STRONG})
    assert r.status_code == 400
    # still logged in, password unchanged
    assert client.get(f"{API}/auth/me", headers=_bearer(t["access_token"])).status_code == 200
    row = db.query(AuditRecord).filter(AuditRecord.action == "auth.password_change", AuditRecord.outcome == "denied").first()
    assert row is not None and "not-the-password-1" not in str(row.context_metadata)


def test_change_password_applies_policy_and_rejects_same_password(client, seeded_users, test_password):
    t = _login(client, "viewer", test_password).json()
    h = _bearer(t["access_token"])
    assert client.post(f"{API}/auth/change-password", headers=h, json={"current_password": test_password, "new_password": "short1"}).status_code == 422
    assert client.post(f"{API}/auth/change-password", headers=h, json={"current_password": test_password, "new_password": test_password}).status_code == 422


def test_self_revoke_sessions_signs_out_everywhere(client, seeded_users, test_password):
    a = _login(client, "analyst", test_password).json()
    b = _login(client, "analyst", test_password).json()
    assert client.post(f"{API}/auth/revoke-sessions", headers=_bearer(a["access_token"])).status_code == 204
    assert client.get(f"{API}/auth/me", headers=_bearer(b["access_token"])).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": b["refresh_token"]}).status_code == 401
    assert _login(client, "analyst", test_password).status_code == 200  # can sign in again


def test_admin_revoke_sessions_for_user(client, seeded_users, tokens, auth_header, test_password):
    v = _login(client, "viewer", test_password).json()
    r = client.post(f"{API}/users/{seeded_users['viewer'].id}/revoke-sessions", headers=auth_header(tokens, "admin"))
    assert r.status_code == 204
    assert client.get(f"{API}/auth/me", headers=_bearer(v["access_token"])).status_code == 401
    # non-admin cannot
    assert client.post(f"{API}/users/{seeded_users['viewer'].id}/revoke-sessions", headers=auth_header(tokens, "analyst")).status_code == 403


def test_admin_reset_password_revokes_and_never_echoes(client, db, seeded_users, tokens, auth_header, test_password):
    v = _login(client, "viewer", test_password).json()
    r = client.post(f"{API}/users/{seeded_users['viewer'].id}/reset-password", headers=auth_header(tokens, "admin"),
                    json={"new_password": STRONG})
    assert r.status_code == 204 and r.content == b""
    assert client.get(f"{API}/auth/me", headers=_bearer(v["access_token"])).status_code == 401
    assert _login(client, "viewer", STRONG).status_code == 200
    rows = db.query(AuditRecord).filter(AuditRecord.action == "user.password_reset").all()
    assert rows and STRONG not in str([x.context_metadata for x in rows])
    weak = client.post(f"{API}/users/{seeded_users['viewer'].id}/reset-password", headers=auth_header(tokens, "admin"), json={"new_password": "abc"})
    assert weak.status_code == 422


def test_role_change_and_disable_revoke_existing_tokens(client, seeded_users, tokens, auth_header, test_password):
    inv = _login(client, "investigator", test_password).json()["access_token"]
    assert client.patch(f"{API}/users/{seeded_users['investigator'].id}", headers=auth_header(tokens, "admin"), json={"role": "viewer"}).status_code == 200
    assert client.get(f"{API}/auth/me", headers=_bearer(inv)).status_code == 401  # old role's token is dead

    ana = _login(client, "analyst", test_password).json()["access_token"]
    assert client.patch(f"{API}/users/{seeded_users['analyst'].id}", headers=auth_header(tokens, "admin"), json={"is_active": False}).status_code == 200
    assert client.get(f"{API}/auth/me", headers=_bearer(ana)).status_code == 401


def test_display_name_change_does_not_revoke(client, seeded_users, tokens, auth_header, test_password):
    v = _login(client, "viewer", test_password).json()["access_token"]
    client.patch(f"{API}/users/{seeded_users['viewer'].id}", headers=auth_header(tokens, "admin"), json={"display_name": "Renamed"})
    assert client.get(f"{API}/auth/me", headers=_bearer(v)).status_code == 200


def test_legacy_token_without_tv_claim_still_valid_until_first_revocation(client, seeded_users):
    s = get_settings()
    user = seeded_users["viewer"]
    legacy = jwt.encode({"sub": user.id, "role": "viewer", "type": "access", "exp": 4102444800}, s.SECRET_KEY, algorithm=s.ALGORITHM)
    assert client.get(f"{API}/auth/me", headers=_bearer(legacy)).status_code == 200


def test_refresh_token_cannot_be_used_as_access_and_vice_versa(client, seeded_users, test_password):
    t = _login(client, "viewer", test_password).json()
    assert client.get(f"{API}/auth/me", headers=_bearer(t["refresh_token"])).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t["access_token"]}).status_code == 401


def test_tampered_and_garbage_tokens_rejected(client, seeded_users, test_password):
    t = _login(client, "viewer", test_password).json()["access_token"]
    head, body, sig = t.split(".")
    assert client.get(f"{API}/auth/me", headers=_bearer(f"{head}.{body}.{sig[:-3]}abc")).status_code == 401
    assert client.get(f"{API}/auth/me", headers=_bearer("not.a.jwt")).status_code == 401
    forged = jwt.encode({"sub": seeded_users["viewer"].id, "role": "administrator", "type": "access", "tv": 0, "exp": 4102444800}, "wrong-key", algorithm="HS256")
    assert client.get(f"{API}/auth/me", headers=_bearer(forged)).status_code == 401


def test_token_role_claim_is_not_trusted(client, seeded_users):
    """A validly-signed token that LIES about the role still gets the DB role."""
    s = get_settings()
    u = seeded_users["viewer"]
    tok = jwt.encode({"sub": u.id, "role": "administrator", "type": "access", "tv": 0, "exp": 4102444800}, s.SECRET_KEY, algorithm=s.ALGORITHM)
    assert client.get(f"{API}/audit", headers=_bearer(tok)).status_code == 403


# ---- login behaviour --------------------------------------------------------

def test_disabled_account_state_not_revealed_without_correct_password(client, db, seeded_users, tokens, auth_header, test_password):
    client.patch(f"{API}/users/{seeded_users['viewer'].id}", headers=auth_header(tokens, "admin"), json={"is_active": False})
    wrong = _login(client, "viewer", "totally-wrong-pass-1")
    assert wrong.status_code == 401 and wrong.json()["detail"] == "Invalid credentials"
    right = _login(client, "viewer", test_password)
    assert right.status_code == 401 and right.json()["detail"] == "Account is disabled"


def test_unknown_user_login_does_same_hash_work(client, seeded_users, monkeypatch):
    from app.services import user_service
    calls = []
    real = user_service.verify_password
    monkeypatch.setattr(user_service, "verify_password", lambda p, h: calls.append(1) or real(p, h))
    assert _login(client, "ghost-user", "whatever-pass-1").status_code == 401
    assert len(calls) == 1  # a dummy bcrypt verification happened


def test_failed_login_audit_does_not_store_identifier_or_password(client, db, seeded_users, caplog):
    secret_typed_as_username = "MyRealPassword!987"
    with caplog.at_level(logging.DEBUG):
        _login(client, secret_typed_as_username, "another-secret-xyz1")
    rows = db.query(AuditRecord).filter(AuditRecord.action == "auth.login").all()
    blob = str([r.context_metadata for r in rows]) + caplog.text
    assert secret_typed_as_username not in blob and "another-secret-xyz1" not in blob
    assert any("identifier_sha256_prefix" in r.context_metadata for r in rows)


def test_failed_login_for_known_user_is_visible_to_that_orgs_admin_only(client, db, seeded_users, tokens, auth_header):
    _login(client, "viewer", "bad-password-123")
    page = client.get(f"{API}/audit?action=auth.login&outcome=denied", headers=auth_header(tokens, "admin")).json()
    assert page["total"] >= 1
    assert all(i["organization_id"] == seeded_users["admin"].organization_id for i in page["items"])


# ---- account administration safety --------------------------------------------

def test_cannot_disable_or_demote_self(client, seeded_users, tokens, auth_header):
    me = seeded_users["admin"].id
    assert client.patch(f"{API}/users/{me}", headers=auth_header(tokens, "admin"), json={"is_active": False}).status_code == 409
    assert client.patch(f"{API}/users/{me}", headers=auth_header(tokens, "admin"), json={"role": "viewer"}).status_code == 409
    assert client.patch(f"{API}/users/{me}", headers=auth_header(tokens, "admin"), json={"display_name": "Still Me"}).status_code == 200


def test_cannot_demote_or_disable_last_active_admin(client, db, seeded_users, tokens, auth_header):
    from app.services import user_service
    second = user_service.create_user(db, organization_id=seeded_users["admin"].organization_id, username="admin2",
                                      email="admin2@test.example.com", display_name="A2", password=STRONG, role="administrator")
    db.commit()
    t2 = _login(client, "admin2", STRONG).json()["access_token"]
    # admin2 may demote the original admin (two admins exist)...
    assert client.patch(f"{API}/users/{seeded_users['admin'].id}", headers=_bearer(t2), json={"role": "analyst"}).status_code == 200
    # ...but now admin2 is the LAST admin: another admin-capable actor cannot remove them.
    # (the demoted admin has no USER_MANAGE any more, so emulate via service-level guard)
    db.expire_all()
    with pytest.raises(user_service.AccessChangeError):
        user_service.check_access_change(db, db.get(User, second.id), acting_user_id="someone-else", role="viewer", is_active=None)
    with pytest.raises(user_service.AccessChangeError):
        user_service.check_access_change(db, db.get(User, second.id), acting_user_id="someone-else", role=None, is_active=False)


def test_refused_access_change_is_audited_as_denied(client, db, seeded_users, tokens, auth_header):
    client.patch(f"{API}/users/{seeded_users['admin'].id}", headers=auth_header(tokens, "admin"), json={"is_active": False})
    row = db.query(AuditRecord).filter(AuditRecord.action == "user.update", AuditRecord.outcome == "denied").first()
    assert row is not None


def test_user_update_audit_has_before_and_after(client, db, seeded_users, tokens, auth_header):
    client.patch(f"{API}/users/{seeded_users['viewer'].id}", headers=auth_header(tokens, "admin"), json={"role": "analyst"})
    row = db.query(AuditRecord).filter(AuditRecord.action == "user.update", AuditRecord.outcome == "success").first()
    assert row.context_metadata["before"]["role"] == "viewer" and row.context_metadata["after"]["role"] == "analyst"
    assert row.context_metadata["sessions_revoked"] is True


def test_access_history_endpoint_org_scoped_and_admin_only(client, seeded_users, tokens, auth_header):
    target = seeded_users["analyst"].id
    client.patch(f"{API}/users/{target}", headers=auth_header(tokens, "admin"), json={"role": "investigator"})
    ok = client.get(f"{API}/users/{target}/access-history", headers=auth_header(tokens, "admin"))
    assert ok.status_code == 200 and any(i["action"] == "user.update" for i in ok.json())
    assert client.get(f"{API}/users/{target}/access-history", headers=auth_header(tokens, "viewer")).status_code == 403


def test_role_matrix_endpoint_admin_only(client, seeded_users, tokens, auth_header):
    ok = client.get(f"{API}/security/roles", headers=auth_header(tokens, "admin"))
    assert ok.status_code == 200
    roles = {r["role"]: set(r["permissions"]) for r in ok.json()["roles"]}
    assert "audit:read" in roles["administrator"] and "audit:read" not in roles["analyst"]
    assert client.get(f"{API}/security/roles", headers=auth_header(tokens, "analyst")).status_code == 403


# ---- route-level authorization coverage --------------------------------------------

_PUBLIC = {("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/refresh"), ("GET", "/api/v1/health/live"), ("GET", "/api/v1/health/ready")}


def _dependency_names(dependant, acc=None):
    acc = acc if acc is not None else set()
    for d in dependant.dependencies:
        if d.call is not None:
            acc.add(getattr(d.call, "__qualname__", repr(d.call)))
        _dependency_names(d, acc)
    return acc


def test_every_route_requires_authentication_or_is_explicitly_public():
    """Fails if someone adds a route with no auth dependency at all."""
    from fastapi.routing import APIRoute
    from app.main import app

    unprotected = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        names = _dependency_names(route.dependant)
        authed = any(n.startswith(("get_current_user", "require_permission.<locals>._check", "require_device_auth")) for n in names)
        for m in route.methods - {"HEAD", "OPTIONS"}:
            if not authed and (m, route.path) not in _PUBLIC:
                unprotected.append((m, route.path))
    assert unprotected == []


def test_unauthenticated_requests_get_401_everywhere_sampled(client):
    for method, path in [("GET", "/users"), ("GET", "/audit"), ("GET", "/media"), ("GET", "/events"), ("GET", "/scenarios"),
                         ("GET", "/lifecycle/policies"), ("GET", "/security/config"), ("POST", "/auth/change-password"),
                         ("GET", "/media/abc/content"), ("GET", "/investigations")]:
        r = client.request(method, API + path, json={} if method == "POST" else None)
        assert r.status_code == 401, (method, path, r.status_code)


def test_denied_operation_is_audited_without_body_or_secrets(client, db, seeded_users, tokens, auth_header):
    r = client.post(f"{API}/users", headers=auth_header(tokens, "viewer"),
                    json={"username": "x1x1", "email": "x@test.example.com", "display_name": "x", "password": "SecretBody-123", "role": "viewer"})
    assert r.status_code == 403
    row = db.query(AuditRecord).filter(AuditRecord.action == "authz.denied").order_by(AuditRecord.created_at.desc()).first()
    assert row.outcome == "denied" and row.actor_user_id == seeded_users["viewer"].id
    assert row.context_metadata["permission"] == "user:manage" and row.context_metadata["route"] == "/api/v1/users"
    assert "SecretBody-123" not in str(row.context_metadata)


def test_denied_audit_failure_does_not_mask_403(client, seeded_users, tokens, auth_header, monkeypatch):
    from app.services import audit_service
    monkeypatch.setattr(audit_service, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit down")))
    assert client.get(f"{API}/audit", headers=auth_header(tokens, "viewer")).status_code == 403


def test_decode_token_carries_version_claim(seeded_users):
    tok = create_access_token(seeded_users["viewer"].id, "viewer", 3)
    assert decode_token(tok)["tv"] == 3


def test_alg_none_other_algorithm_and_no_expiry_tokens_rejected(client, seeded_users):
    s = get_settings()
    uid = seeded_users["viewer"].id
    claims = {"sub": uid, "role": "viewer", "type": "access", "tv": 0, "exp": 4102444800}
    unsigned = jwt.encode(claims, key=None, algorithm="none")
    assert client.get(f"{API}/auth/me", headers=_bearer(unsigned)).status_code == 401
    hs512 = jwt.encode(claims, s.SECRET_KEY, algorithm="HS512")
    assert client.get(f"{API}/auth/me", headers=_bearer(hs512)).status_code == 401
    no_exp = jwt.encode({k: v for k, v in claims.items() if k != "exp"}, s.SECRET_KEY, algorithm=s.ALGORITHM)
    assert client.get(f"{API}/auth/me", headers=_bearer(no_exp)).status_code == 401
    expired = jwt.encode({**claims, "exp": 1000}, s.SECRET_KEY, algorithm=s.ALGORITHM)
    assert client.get(f"{API}/auth/me", headers=_bearer(expired)).status_code == 401
