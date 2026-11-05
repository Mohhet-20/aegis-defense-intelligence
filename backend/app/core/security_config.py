"""Security-configuration report (/J).

`evaluate()` inspects the live Settings and returns findings. It NEVER
returns a secret value -- only booleans ("is a key configured") and
non-secret numbers. `startup_blockers()` is the subset that makes a
PRODUCTION process refuse to start.
"""
from __future__ import annotations

from typing import Any

from app.core.config import Settings

DEFAULT_SECRET = "dev-only-secret-change-me-in-production"
_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _f(fid: str, severity: str, title: str, detail: str, fix: str) -> dict:
    return {"id": fid, "severity": severity, "title": title, "detail": detail, "recommendation": fix}


def evaluate(s: Settings) -> dict[str, Any]:
    prod = s.ENVIRONMENT.lower() == "production"
    sev = lambda in_prod, otherwise="medium": in_prod if prod else otherwise  # noqa: E731
    findings: list[dict] = []

    if s.SECRET_KEY == DEFAULT_SECRET:
        findings.append(_f("secret_key_default", sev("critical", "high"), "SECRET_KEY is the development placeholder",
                           "Anyone who knows the placeholder can forge tokens.", "Set SECRET_KEY to a random value of at least 32 bytes."))
    elif len(s.SECRET_KEY) < 32:
        findings.append(_f("secret_key_short", sev("critical", "medium"), "SECRET_KEY is shorter than 32 characters",
                           "Short HMAC keys are easier to brute-force.", "Generate one with `python -c \"import secrets;print(secrets.token_urlsafe(48))\"`."))
    if any(len(k) < 32 for k in s.previous_secret_keys):
        findings.append(_f("secret_key_previous_short", sev("critical", "medium"), "A SECRET_KEY_PREVIOUS entry is shorter than 32 characters",
                           "Tokens signed with a weak former key would still be accepted.", "Remove it or wait out the grace period before rotating again."))
    if "*" in s.cors_origins_list:
        findings.append(_f("cors_wildcard", sev("critical", "high"), "CORS allows every origin",
                           "Combined with credentialed requests this lets any site call the API from a browser.", "List explicit origins in CORS_ALLOWED_ORIGINS."))
    elif prod and any(o.startswith("http://") for o in s.cors_origins_list):
        findings.append(_f("cors_http_origin", "medium", "A CORS origin uses plain http", "Traffic to/from that origin is unencrypted.", "Serve the frontend over https."))
    if s.DATABASE_URL.startswith("sqlite"):
        findings.append(_f("database_sqlite", sev("medium", "info"), "SQLite database in use",
                           "Fine for development and single-node pilots; no row-level security, limited concurrency.", "Use PostgreSQL for shared deployments."))
    if s.docs_enabled:
        findings.append(_f("api_docs_enabled", sev("medium", "info"), "Interactive API docs are enabled",
                           "/api/docs and /api/openapi.json reveal the full route surface.", "Leave ENABLE_API_DOCS unset (auto-off in production) or set it false."))
    if s.ACCESS_TOKEN_EXPIRE_MINUTES > 60:
        findings.append(_f("access_token_long", "medium", "Access-token lifetime exceeds 60 minutes", "A stolen access token stays valid that long (revocation is by user, not per token).", "Use 15-30 minutes."))
    if s.REFRESH_TOKEN_EXPIRE_MINUTES > 60 * 24 * 30:
        findings.append(_f("refresh_token_long", "medium", "Refresh-token lifetime exceeds 30 days", "Refresh tokens are not rotated.", "Shorten REFRESH_TOKEN_EXPIRE_MINUTES."))
    if s.PASSWORD_MIN_LENGTH < 10:
        findings.append(_f("password_min_short", "medium", "PASSWORD_MIN_LENGTH below 10", "Weak minimum for new passwords.", "Use 12 or more."))
    if s.COPILOT_PROVIDER != "none" and s.COPILOT_ALLOW_EXTERNAL:
        findings.append(_f("external_provider_enabled", "info", "External copilot provider is enabled",
                           "Retrieved record text is sent to a third party when generating answers.", "Confirm this is permitted for the data classification in use."))
    elif s.COPILOT_PROVIDER != "none" and not s.COPILOT_ALLOW_EXTERNAL:
        findings.append(_f("external_provider_blocked", "info", "External provider configured but egress not allowed", "COPILOT_ALLOW_EXTERNAL=false keeps data local.", "No action needed."))
    if not s.SECURITY_HEADERS_ENABLED:
        findings.append(_f("security_headers_off", "medium", "Security response headers are disabled", "", "Set SECURITY_HEADERS_ENABLED=true."))
    if s.TRUST_FORWARDED_HEADERS:
        findings.append(_f("forwarded_headers_trusted", "low", "X-Forwarded-For is trusted", "Safe only when a proxy you control strips client-supplied values.", "Disable unless behind a trusted reverse proxy."))
    if not s.LIFECYCLE_REQUIRE_SEPARATE_APPROVER:
        findings.append(_f("lifecycle_self_approval", "medium", "Lifecycle self-approval is allowed", "One administrator can request and approve a deletion.", "Keep LIFECYCLE_REQUIRE_SEPARATE_APPROVER=true when more than one administrator exists."))
    if s.MAX_REQUEST_BODY_BYTES > 50 * 1024 * 1024:
        findings.append(_f("request_limit_large", "low", "Large non-upload request limit", "", "Keep MAX_REQUEST_BODY_BYTES modest."))
    findings.sort(key=lambda f: _ORDER[f["severity"]])
    return {
        "environment": s.ENVIRONMENT,
        "findings": findings,
        "settings": {
            "access_token_minutes": s.ACCESS_TOKEN_EXPIRE_MINUTES,
            "refresh_token_minutes": s.REFRESH_TOKEN_EXPIRE_MINUTES,
            "jwt_algorithm": s.ALGORITHM,
            "auth_rate_limit": s.RATE_LIMIT_AUTH,
            "max_failed_logins": s.MAX_FAILED_LOGIN_ATTEMPTS,
            "lockout_minutes": s.ACCOUNT_LOCKOUT_MINUTES,
            "password_min_length": s.PASSWORD_MIN_LENGTH,
            "max_request_body_bytes": s.MAX_REQUEST_BODY_BYTES,
            "max_upload_request_bytes": s.MAX_UPLOAD_REQUEST_BYTES,
            "max_image_bytes": s.CV_MAX_IMAGE_UPLOAD_BYTES,
            "max_video_bytes": s.CV_MAX_VIDEO_UPLOAD_BYTES,
            "max_page_size": s.MAX_PAGE_SIZE,
            "cors_origin_count": len(s.cors_origins_list),
            "cors_allows_wildcard": "*" in s.cors_origins_list,
            "api_docs_enabled": s.docs_enabled,
            "security_headers_enabled": s.SECURITY_HEADERS_ENABLED,
            "trust_forwarded_headers": s.TRUST_FORWARDED_HEADERS,
            "database_dialect": s.DATABASE_URL.split(":", 1)[0].split("+", 1)[0],
            "audit_write_failure_policy": "transactional: the audit row shares the change's transaction (fail-closed); only the authz.denied recorder is best-effort",
            "audit_retention_days": s.AUDIT_RETENTION_DAYS or None,
            "copilot_provider": s.COPILOT_PROVIDER,
            "copilot_external_egress_allowed": s.COPILOT_ALLOW_EXTERNAL,
            "lifecycle_separate_approver": s.LIFECYCLE_REQUIRE_SEPARATE_APPROVER,
        },
        "secrets_configured": {  # booleans only -- values are never exposed
            "secret_key_is_custom": s.SECRET_KEY != DEFAULT_SECRET,
            "copilot_api_key_set": bool(s.COPILOT_API_KEY),
        },
        "not_implemented": [
            "multi-factor authentication", "refresh-token rotation / per-token revocation",
            "tamper-evident (hash-chained) audit log", "encryption of stored media at rest",
            "per-tenant database isolation (row-level checks are application-enforced)",
        ],
    }


def startup_blockers(s: Settings) -> list[str]:
    """Titles of critical findings; non-empty + production => refuse to start."""
    if s.ENVIRONMENT.lower() != "production":
        return []
    return [f["title"] for f in evaluate(s)["findings"] if f["severity"] == "critical"]
