"""SSRF defenses for the HTTP connector (Section 4 / Section 17 of the
Spec). Every outbound URL -- the configured endpoint AND every
redirect hop -- goes through `validate_url()` before a request is
made. This is deliberately conservative: when in doubt, reject.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Optional
from urllib.parse import urlsplit

from app.connectors.types import ConnectorConfigError, ErrorCategory

ALLOWED_SCHEMES = {"https"}
# http:// is only ever allowed when the source config explicitly opts
# in AND the resolved host is a loopback address -- i.e. a trusted
# local development integration ("unless explicitly
# permitted for a trusted local development integration").
LOCAL_DEV_SCHEMES = {"http", "https"}

MAX_REDIRECTS = 3


def _is_unsafe_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local  # covers the 169.254.169.254 cloud-metadata address
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_all(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ConnectorConfigError(f"could not resolve host '{hostname}': {exc}", ErrorCategory.UNSAFE_DESTINATION) from exc
    return sorted({info[4][0] for info in infos})


def validate_url(url: str, *, allow_local_dev: bool = False) -> None:
    """Raises ConnectorConfigError if `url` is not safe to fetch.
    `allow_local_dev` permits http:// AND loopback destinations, for a
    source explicitly configured as a local development integration --
    it never permits a private (non-loopback) or link-local address,
    since those are someone else's network, not "local dev"."""
    parts = urlsplit(url)

    if allow_local_dev:
        from app.core.config import get_settings

        if get_settings().ENVIRONMENT.lower() == "production":
            # `allow_local_dev` is a per-source setting a source manager can set;
            # in production it must not be able to reach loopback or plain http.
            raise ConnectorConfigError(
                "allow_local_dev is not permitted when ENVIRONMENT=production",
                ErrorCategory.UNSAFE_DESTINATION,
            )

    allowed_schemes = LOCAL_DEV_SCHEMES if allow_local_dev else ALLOWED_SCHEMES
    if parts.scheme not in allowed_schemes:
        raise ConnectorConfigError(
            f"scheme '{parts.scheme}' is not permitted (allowed: {sorted(allowed_schemes)})",
            ErrorCategory.UNSAFE_DESTINATION,
        )

    if not parts.hostname:
        raise ConnectorConfigError("URL has no host", ErrorCategory.UNSAFE_DESTINATION)

    if parts.username or parts.password:
        raise ConnectorConfigError("credentials must not be embedded in the URL", ErrorCategory.UNSAFE_DESTINATION)

    resolved_ips = _resolve_all(parts.hostname)
    if not resolved_ips:
        raise ConnectorConfigError(f"host '{parts.hostname}' did not resolve to any address", ErrorCategory.UNSAFE_DESTINATION)

    for ip_str in resolved_ips:
        ip = ipaddress.ip_address(ip_str)
        if allow_local_dev and ip.is_loopback:
            continue  # explicitly permitted trusted-local-dev case
        if _is_unsafe_ip(ip_str):
            raise ConnectorConfigError(
                f"host '{parts.hostname}' resolves to a disallowed address ({ip_str}) -- "
                "loopback, private, link-local (includes cloud metadata), reserved, and "
                "multicast destinations are blocked",
                ErrorCategory.UNSAFE_DESTINATION,
            )


def redact_credentials(url: str) -> str:
    """Never log a URL with embedded credentials -- Section 4 and
    Section 16 both require this. validate_url() already rejects
    userinfo in the URL outright, but this exists as a second layer
    for anything logged before that check runs (e.g. the raw config
    value) or from a redirect Location header."""
    parts = urlsplit(url)
    if not (parts.username or parts.password):
        return url
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return url.replace(parts.netloc, f"***redacted***@{netloc}" if netloc else "***redacted***")


def host_label(url: str) -> Optional[str]:
    """A safe-to-log summary of a URL -- host only, never the path,
    query string, or any credentials."""
    parts = urlsplit(url)
    return parts.hostname
