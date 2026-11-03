"""Phase 18: first-administrator bootstrap for production deployments."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.audit import AuditRecord
from app.services.user_service import DuplicateUserError, PasswordPolicyError
from scripts.bootstrap_admin import BootstrapRefused, bootstrap

GOOD = "Str0ng-Bootstrap-Pass!"


def test_bootstrap_creates_org_and_admin_who_can_log_in(client, db):
    org, user = bootstrap(db, organization="Fresh Org", username="root", email="root@fresh.example.org", display_name="Root", password=GOOD)
    r = client.post("/api/v1/auth/login", json={"username_or_email": "root", "password": GOOD})
    assert r.status_code == 200
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["role"] == "administrator"
    audit = db.execute(select(AuditRecord).where(AuditRecord.action == "user.bootstrap_admin")).scalars().all()
    assert len(audit) == 1 and audit[0].organization_id == org.id
    assert GOOD not in str(audit[0].context_metadata)


def test_bootstrap_enforces_password_policy_and_leaves_nothing_behind(db):
    from app.models.user import User

    with pytest.raises(PasswordPolicyError):
        bootstrap(db, organization="Weak Org", username="weak", email="weak@x.example.org", display_name="W", password="short")
    db.rollback()
    assert db.execute(select(User).where(User.username == "weak")).first() is None


def test_bootstrap_refuses_a_second_administrator_for_the_same_organization(db):
    bootstrap(db, organization="Once Org", username="first", email="first@x.example.org", display_name="F", password=GOOD)
    with pytest.raises(BootstrapRefused):
        bootstrap(db, organization="Once Org", username="second", email="second@x.example.org", display_name="S", password=GOOD)


def test_bootstrap_refuses_duplicate_username(db):
    bootstrap(db, organization="Org One", username="same", email="a@x.example.org", display_name="A", password=GOOD)
    with pytest.raises(DuplicateUserError):
        bootstrap(db, organization="Org Two", username="same", email="b@x.example.org", display_name="B", password=GOOD)


def test_cli_refuses_without_a_password_source(monkeypatch, capsys):
    from scripts import bootstrap_admin

    monkeypatch.delenv("AEGIS_BOOTSTRAP_PASSWORD", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert bootstrap_admin.main(["--organization", "X", "--username", "u", "--email", "u@x.example.org"]) == 2
    assert "AEGIS_BOOTSTRAP_PASSWORD" in capsys.readouterr().err


def test_cli_main_creates_the_admin_end_to_end_and_never_prints_the_password(monkeypatch, capsys, SessionLocalForTest, client):
    # Regression: main() read ORM attributes after closing the session (DetachedInstanceError)
    # even though the administrator had already been committed.
    from scripts import bootstrap_admin

    monkeypatch.setenv("AEGIS_BOOTSTRAP_PASSWORD", GOOD)
    monkeypatch.setattr("app.db.session.SessionLocal", SessionLocalForTest)
    code = bootstrap_admin.main(["--organization", "Cli Org", "--username", "cliadmin", "--email", "cli@x.example.org"])
    out = capsys.readouterr()
    assert code == 0 and "cliadmin" in out.out and GOOD not in out.out + out.err
    assert client.post("/api/v1/auth/login", json={"username_or_email": "cliadmin", "password": GOOD}).status_code == 200
    # a second run is refused with exit status 1, not a traceback
    assert bootstrap_admin.main(["--organization", "Cli Org", "--username", "other", "--email", "o@x.example.org"]) == 1
