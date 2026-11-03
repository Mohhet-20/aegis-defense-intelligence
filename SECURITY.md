# Security policy

## Supported versions

| Version | Supported |
|---|---|
| `1.0.0-rc.3` (branch `release/final-stabilization`) | yes -- current release candidate |
| `1.0.0-rc.1` and anything older (build snapshots, `main` = phase 14 baseline) | no |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

- If this repository is hosted on GitHub, use **Security → Report a vulnerability** (private
  vulnerability reporting) once the owner has enabled it in the repository settings.
- Otherwise contact the repository owner privately through the hosting platform.

Include: affected version or commit, the component (endpoint, page, script), steps to reproduce with
**synthetic data only**, impact, and any suggested fix. Never include real credentials, personal data
or operational records. Expect an acknowledgement when the owner is available; this is a
personal/portfolio project with no guaranteed response time.

## Scope and intended use

AEGIS is a **software demonstration and research platform** for analyst decision support. It is not
an autonomous defense system, not an operationally validated decision system, and contains no
targeting, weapon-control or automated-action capability. Model output is advisory. Do not deploy it
to process real intelligence, personal data or evidence without your own security review.

## Security model (summary)

- Authentication: short-lived JWT access tokens kept in browser memory only; refresh token in an
  HttpOnly, SameSite=Strict cookie scoped to `/api/v1/auth` (Secure in production) and accepted only
  with a custom header (CSRF guard); bcrypt hashing, account lockout, per-address rate limits,
  per-user session revocation, `SECRET_KEY` rotation with a verify-only grace period.
- Authorization: four roles enforced **on the server** for every operation; per-organization
  isolation on every query (tested with cross-tenant sweeps over all API operations).
- Uploads: signature-based type detection, size and dimension limits, content-addressed private
  storage that is never served statically; downloads require authentication; an orphan-file sweeper.
- Model supply chain: pretrained weights and evaluation data are pinned by SHA-256 and verified before
  use; only expected archive members are extracted; nothing is fetched at inference time.
- Errors never echo submitted values or stack traces; logs redact secrets.
- Production mode refuses to start with a missing, placeholder or short `SECRET_KEY`, refuses `*`
  CORS, disables API docs by default and never auto-migrates.
- Frontend: Content-Security-Policy with `script-src 'self'` (no inline script), served by the nginx
  container and browser-tested via `npm run preview`.
- Repository and dependencies: `detect-secrets` (reviewed baseline), pip-audit, bandit and
  `npm audit` run in CI; all clean at release. `.gitignore` excludes env files, databases, media,
  model weights, evaluation data and build output.

## Known limitations

The authoritative list, with severities, is [`docs/security/KNOWN_RISKS.md`](docs/security/KNOWN_RISKS.md).
Most relevant: audit records are append-only in the application but not tamper-proof; rate limits
are per process; no MFA; the detector is not validated on operational imagery; container images and
the CI workflow have not yet been executed.
