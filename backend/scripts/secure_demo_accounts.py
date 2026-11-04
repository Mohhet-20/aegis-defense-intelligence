"""Lock the public demo's accounts before the server is announced ready (run by scripts/demo_server.py).

scripts/seed.py gives the shared demo accounts the documented development password, which the startup walkthrough
and the detector showcase use to load data. On a public deployment that password is in the public repository, so
this script then:

* gives every shared demo account a fresh random password that is never shown or stored anywhere, and bumps its
  token version so the sessions the startup scripts opened stop working;
* creates the owner's administrator from AEGIS_ADMIN_USERNAME / AEGIS_ADMIN_PASSWORD (hosting secrets), if both
  are set. Without them there is no administrator account a visitor could reach.

Visitors get in through POST /api/v1/demo/session, which opens a session for the analyst account with no password.
Refuses to run unless DEMO_MODE is on.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.demo import DEMO_ACCOUNTS  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402


def main() -> int:
    if not get_settings().DEMO_MODE:
        raise SystemExit("Refusing: DEMO_MODE is off. This script only locks a public demo's shared accounts.")
    db = SessionLocal()
    try:
        accounts = db.query(User).filter(User.username.in_(list(DEMO_ACCOUNTS))).all()
        for user in accounts:
            user.password_hash = hash_password(secrets.token_urlsafe(32))
            user.token_version = int(user.token_version or 0) + 1
        print(f"[demo] locked {len(accounts)} shared accounts (random passwords, sessions revoked)", flush=True)

        username = os.environ.get("AEGIS_ADMIN_USERNAME", "").strip().lower()
        password = os.environ.get("AEGIS_ADMIN_PASSWORD", "")
        if username and password:
            if username in DEMO_ACCOUNTS:
                raise SystemExit("AEGIS_ADMIN_USERNAME must not be one of the shared demo account names")
            if len(password) < 12:
                raise SystemExit("AEGIS_ADMIN_PASSWORD must be at least 12 characters")
            org_id = accounts[0].organization_id if accounts else None
            if org_id is None:
                raise SystemExit("no demo organisation to add the administrator to")
            owner = db.query(User).filter_by(username=username).first()
            if owner is None:
                owner = User(organization_id=org_id, username=username, email=f"{username}@owner.invalid",
                             display_name="Owner", role="administrator", is_active=True,
                             password_hash=hash_password(password))
                db.add(owner)
            else:
                owner.password_hash = hash_password(password)
                owner.role, owner.is_active = "administrator", True
            print(f"[demo] owner administrator '{username}' ready", flush=True)
        else:
            print("[demo] AEGIS_ADMIN_USERNAME/AEGIS_ADMIN_PASSWORD not set: no administrator account", flush=True)
        db.commit()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
