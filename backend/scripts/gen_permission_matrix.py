"""Regenerates docs/security/ROLES_AND_PERMISSIONS.md from app/core/security.py."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core.security import Permission, ROLE_PERMISSIONS, Role  # noqa: E402

NOTES = (ROOT.parent / "docs/security/ROLES_AND_PERMISSIONS.md").read_text().split("## Notes", 1)[1]
rows = [
    "# Roles and permissions", "",
    "_Generated from `app/core/security.py` (`ROLE_PERMISSIONS`) -- regenerate with `python scripts/gen_permission_matrix.py`. The code is authoritative; this file is a snapshot._", "",
    "Four fixed roles; the role→permission table is defined in code and is **not** editable through the API. Administrator holds every permission (`set(Permission)`), so any permission added in future is automatically administrator-only until explicitly granted to another role.", "",
    "| Permission | Administrator | Analyst | Investigator | Viewer |", "|---|:-:|:-:|:-:|:-:|",
]
for p in sorted(Permission, key=lambda x: x.value):
    rows.append(f"| `{p.value}` | " + " | ".join("✔" if p in ROLE_PERMISSIONS[r] else "" for r in (Role.ADMINISTRATOR, Role.ANALYST, Role.INVESTIGATOR, Role.VIEWER)) + " |")
(ROOT.parent / "docs/security/ROLES_AND_PERMISSIONS.md").write_text("\n".join(rows) + "\n\n## Notes" + NOTES)
print("written")
