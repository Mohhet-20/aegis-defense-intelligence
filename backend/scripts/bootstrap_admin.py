"""Create the first organization and administrator for a NEW deployment.

Production has no demo accounts (scripts/seed.py refuses to run there), so
this is the supported way to obtain the first login. Run it once, after
`alembic upgrade head`:

    AEGIS_BOOTSTRAP_PASSWORD='...' python scripts/bootstrap_admin.py \\
        --organization "Example Org" --username admin --email admin@example.org

The password is read from the AEGIS_BOOTSTRAP_PASSWORD environment variable or,
if that is unset and stdin is a terminal, prompted for. It is never accepted on
the command line (it would land in shell history and process listings) and is
never printed. The password policy is enforced. The script refuses to run when
the target organization already has an administrator, so it cannot be used to
add backdoor administrators later; use the authenticated /users API for that.
Creation is recorded in the audit log (action `user.bootstrap_admin`).
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


class BootstrapRefused(Exception):
    pass


def bootstrap(db: Session, *, organization: str, username: str, email: str, display_name: str, password: str):
    from app.models.organization import Organization
    from app.models.user import User
    from app.services import audit_service, user_service

    org = db.execute(select(Organization).where(Organization.name == organization)).scalar_one_or_none()
    if org is not None:
        has_admin = db.execute(
            select(User.id).where(User.organization_id == org.id, User.role == "administrator", User.is_active.is_(True)).limit(1)
        ).first()
        if has_admin:
            raise BootstrapRefused(f"organization '{organization}' already has an active administrator; refusing to add another")
    else:
        org = Organization(name=organization, status="active")
        db.add(org)
        db.flush()
    user = user_service.create_user(
        db, organization_id=org.id, username=username, email=email, display_name=display_name, password=password, role="administrator",
    )
    audit_service.record(
        db, action="user.bootstrap_admin", actor_user_id=None, organization_id=org.id, target_type="user", target_id=user.id,
        context_metadata={"username": username, "via": "scripts/bootstrap_admin.py"},
    )
    db.commit()
    return org, user


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--organization", required=True)
    ap.add_argument("--username", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--display-name", default=None)
    a = ap.parse_args(argv)
    password = os.environ.get("AEGIS_BOOTSTRAP_PASSWORD")
    if not password:
        if not sys.stdin.isatty():
            print("Set AEGIS_BOOTSTRAP_PASSWORD or run from a terminal to be prompted.", file=sys.stderr)
            return 2
        password = getpass.getpass("Administrator password: ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords differ.", file=sys.stderr)
            return 2

    from app.db.session import SessionLocal
    from app.services.user_service import DuplicateUserError, PasswordPolicyError

    db = SessionLocal()
    try:
        org, user = bootstrap(db, organization=a.organization, username=a.username, email=a.email,
                              display_name=a.display_name or a.username, password=password)
        org_name, user_name = org.name, user.username  # read before the session closes
    except (BootstrapRefused, DuplicateUserError) as exc:
        db.rollback()
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    except PasswordPolicyError as exc:
        db.rollback()
        print(f"Password rejected: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"Created organization '{org_name}' and administrator '{user_name}'. Log in through the UI or POST /api/v1/auth/login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
