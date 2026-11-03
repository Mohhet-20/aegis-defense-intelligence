"""The one rate limiter instance. Routes decorate with `@limiter.limit(...)`; main.py
registers the same object on `app.state.limiter`. Limits are kept in process memory,
so they apply per backend process (see docs/security/KNOWN_RISKS.md)."""
from __future__ import annotations

from slowapi import Limiter
from starlette.requests import Request

from app.core.config import get_settings


def client_address(request: Request) -> str:
    """The address limits are keyed on.

    By default the socket peer. Behind proxies you control (TRUST_FORWARDED_HEADERS),
    every client would otherwise share the proxy's address -- and one visitor's failed
    logins would lock out everyone -- so the client is read from X-Forwarded-For,
    TRUSTED_PROXY_HOPS entries from the right. Entries further left are client-supplied
    and are never used.
    """
    peer = request.client.host if request.client else "unknown"
    settings = get_settings()
    if not settings.TRUST_FORWARDED_HEADERS:
        return peer
    hops = [h.strip() for h in ",".join(request.headers.getlist("x-forwarded-for")).split(",") if h.strip()]
    if not hops:
        return peer
    return hops[-min(max(settings.TRUSTED_PROXY_HOPS, 1), len(hops))]


limiter = Limiter(key_func=client_address)
