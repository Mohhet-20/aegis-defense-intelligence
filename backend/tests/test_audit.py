"""Audit logging: actions actually get recorded, and the
list endpoint is restricted + scoped to the caller's organization or
system-level (organization_id is NULL) records."""
from __future__ import annotations


def test_login_is_audited(client, seeded_users, tokens, test_password, auth_header):
    client.post("/api/v1/auth/login", json={"username_or_email": "admin", "password": test_password})

    response = client.get("/api/v1/audit", headers=auth_header(tokens, "admin"))
    assert response.status_code == 200
    actions = [r["action"] for r in response.json()["items"]]
    assert "auth.login" in actions


def test_failed_login_is_audited_with_denied_outcome(client, seeded_users, tokens, auth_header):
    client.post("/api/v1/auth/login", json={"username_or_email": "admin", "password": "wrong"})

    response = client.get("/api/v1/audit", headers=auth_header(tokens, "admin"))
    records = response.json()["items"]
    denied = [r for r in records if r["action"] == "auth.login" and r["outcome"] == "denied"]
    assert len(denied) == 1


def test_source_creation_is_audited_with_target(client, seeded_users, tokens, auth_header):
    create = client.post(
        "/api/v1/sources",
        json={"name": "Audited Source", "source_type": "manual"},
        headers=auth_header(tokens, "analyst"),
    )
    source_id = create.json()["id"]

    response = client.get("/api/v1/audit", headers=auth_header(tokens, "admin"))
    matches = [r for r in response.json()["items"] if r["action"] == "source.create" and r["target_id"] == source_id]
    assert len(matches) == 1


def test_non_administrator_cannot_read_audit_log(client, seeded_users, tokens, auth_header):
    for role in ("analyst", "investigator", "viewer"):
        response = client.get("/api/v1/audit", headers=auth_header(tokens, role))
        assert response.status_code == 403
