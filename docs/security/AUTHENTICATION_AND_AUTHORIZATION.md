# Authentication and authorization (Phase 14)

This describes what the code **does** today, and — just as important — what it does not.

## Authentication

| Aspect | Behaviour | Verified by |
|---|---|---|
| Password storage | `bcrypt` (library used directly; input truncated to 72 bytes). Hashes are never returned by any API. | `test_auth.py`, `test_users.py` |
| Password policy (new passwords only) | ≥ `PASSWORD_MIN_LENGTH` (default 10) characters, ≥1 letter, ≥1 digit, not on a small deny-list, must not contain the username/e-mail local part, ≤72 bytes. **Not** a breached-password check. Existing hashes are untouched. | `test_security_p14_auth.py::test_create_user_enforces_password_policy` |
| Login | `POST /auth/login`. Rate-limited (`RATE_LIMIT_AUTH`, default 10/min per client address). Lock-out after `MAX_FAILED_LOGIN_ATTEMPTS` (5) for `ACCOUNT_LOCKOUT_MINUTES` (15). | `test_auth.py` |
| Login error disclosure | Unknown user and wrong password return the identical `Invalid credentials`, and an unknown identifier burns the same bcrypt work (dummy-hash verification) so timing does not distinguish them. "Account is disabled" is revealed **only** after the correct password. A *locked* account reports the lock to anyone who names it (deliberate: needed for support; it does disclose that the account exists). | `test_unknown_user_login_does_same_hash_work`, `test_disabled_account_state_not_revealed_without_correct_password` |
| Tokens | JWT, **HS256 only**, signed with `SECRET_KEY` (PyJWT; the allowed algorithm list is fixed in code, `alg:none`/other algorithms are rejected, `exp` and `sub` are required). Access TTL 30 min, refresh TTL 7 days (configurable). | `test_alg_none_other_algorithm_and_no_expiry_tokens_rejected` |
| Role in the token | Informational only. Every request loads the user from the database and uses the **database** role and `is_active`. | `test_token_role_claim_is_not_trusted` |
| Session invalidation | Each user has `token_version`; every token carries it (`tv`). The version is bumped by: password change, admin password reset, role change, account disablement, and explicit "revoke sessions" (self or admin). A token whose `tv` differs is rejected (401, "Session has been revoked") for **both** access and refresh tokens. Tokens issued before Phase 14 have no `tv` and count as version 0 until the first revocation. | `test_change_password_revokes_all_existing_tokens`, `test_role_change_and_disable_revoke_existing_tokens`, … |
| Refresh | `POST /auth/refresh` returns a new pair. **This is not refresh-token rotation**: the presented refresh token stays valid until it expires or the user's sessions are revoked. A stolen refresh token is therefore usable for up to 7 days unless the user is revoked. | documented limitation |
| Password change | `POST /auth/change-password` (current password required, policy applied, all sessions revoked, fresh pair returned, audited without the password). | tests above |
| Admin account management | `/users` create/update; `/users/{id}/reset-password`, `/revoke-sessions`, `/access-history`. A user cannot change **their own** role or disable themselves, and the **last active administrator** of an organization cannot be demoted or disabled. Refused attempts are audited as `denied`. | `test_cannot_disable_or_demote_self`, `test_cannot_demote_or_disable_last_active_admin` |
| Token storage in the browser | The frontend keeps tokens in memory/session handling defined in `frontend/src/api/client.ts` (pre-existing design; no cookies). Anything readable by page JavaScript is exposed to XSS — see Known risks. | — |
| MFA | **Not implemented.** | — |
| Per-token revocation / deny-list | **Not implemented** (revocation is per user via `token_version`). | — |
| Device authentication | Separate path: `X-Device-Id` + `X-Device-Api-Key`; keys hashed at rest, shown once. See `EDGE_DEVICE_SECURITY.md`. | `test_edge_*` |

### Secret-key rotation
`SECRET_KEY` signs every token. To rotate: set a new value and restart — **all existing tokens become invalid** (users sign in again). There is no dual-key grace period. Procedure and production checks are in `ENVIRONMENT_CONFIGURATION.md`.

## Authorization

* **One mechanism.** Every route except `login`, `refresh`, `health/live`, `health/ready` depends on `require_permission(...)` (human users), `get_current_user` (any signed-in user: `/auth/me`, `/dashboard/summary`) or `require_device_auth` (edge devices). `test_every_route_requires_authentication_or_is_explicitly_public` walks the live FastAPI route table and fails if a new route has none of these.
* **Roles → permissions** are in `app/core/security.py`; see `ROLES_AND_PERMISSIONS.md` for the generated matrix. Read, create/modify, export, run and admin actions use separate permissions.
* **Frontend visibility is not authorization.** Navigation hides admin pages from non-admins for convenience only; the API enforces everything (tests above use no UI).
* **404 vs 403.** A *missing permission* gives `403 Missing permission: …` (the permission name is not sensitive). A record that belongs to another organization, is restricted, or does not exist gives the **same** `404 … not found`. Referenced ids inside request bodies follow the same rule (`app/core/tenancy.py`).
* **Denied operations are audited** (`authz.denied`: actor, role, required permission, method, masked path — never the body, query values or headers). That recorder is deliberately best-effort so an audit failure cannot turn a 403 into a 500.
* **Org context.** `organization_id` always comes from the authenticated user's database row, never from the request.

## Known gaps
See `KNOWN_RISKS.md` (refresh rotation, MFA, no custom roles, global model registry, application-level-only tenant isolation).
