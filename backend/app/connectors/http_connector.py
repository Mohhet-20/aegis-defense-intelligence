"""A safely-configurable HTTP API connector. Disabled
unless a source's config explicitly supplies a `url` -- there is no
default endpoint, and nothing here turns the application into a
general-purpose server-side fetch proxy for a client-supplied address.

Every request this connector makes -- the initial one and any
redirect hop -- is revalidated through app.connectors.url_safety
before it's issued. TLS verification is never disabled. Credentials
are read from environment variables only (never from config.url or
config itself), and are never logged.
"""
from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urljoin

import httpx

from app.connectors.base import BaseConnector
from app.connectors.types import ConnectorConfigError, ConnectorError, ConnectorResult, ErrorCategory, RawRecord
from app.connectors.url_safety import host_label, redact_credentials, validate_url

MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # same bound as a file upload -- Section 17
DEFAULT_TIMEOUT_SECONDS = 10.0
ALLOWED_CONTENT_TYPES = ("application/json",)


class HttpApiConnector(BaseConnector):
    connector_type = "http_api"
    connector_version = "1.0"

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        url = self.config.get("url")
        if not url or not isinstance(url, str):
            errors.append("config.url is required and must be a string")
            return errors

        allow_local_dev = bool(self.config.get("allow_local_dev", False))
        try:
            validate_url(url, allow_local_dev=allow_local_dev)
        except ConnectorConfigError as exc:
            errors.append(str(exc))

        timeout = self.config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 60:
            errors.append("config.timeout_seconds must be a number between 0 and 60")

        auth_env_var = self.config.get("auth_env_var")
        if auth_env_var is not None and not isinstance(auth_env_var, str):
            errors.append("config.auth_env_var must be a string naming an environment variable, never a literal credential")

        return errors

    def _auth_headers(self) -> dict:
        """Credentials come from an environment variable NAMED in the
        config -- never a literal value stored in config_metadata
        ("Never store API keys or passwords in plain-text
        source metadata"). If the named variable isn't set, the
        request simply goes out unauthenticated rather than failing
        config validation -- a source can be registered before its
        secret is provisioned."""
        auth_env_var = self.config.get("auth_env_var")
        if not auth_env_var:
            return {}
        token = os.environ.get(auth_env_var)
        return {"Authorization": f"Bearer {token}"} if token else {}

    def check_connectivity(self) -> tuple[bool, Optional[str]]:
        errors = self.validate_config()
        if errors:
            return False, "; ".join(errors)
        url = self.config["url"]
        timeout = float(self.config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                response = client.head(url, headers=self._auth_headers())
                if response.status_code >= 500:
                    return False, f"endpoint returned HTTP {response.status_code}"
                return True, None
        except httpx.TimeoutException:
            return False, "connection timed out"
        except httpx.HTTPError as exc:
            return False, f"connection failed: {type(exc).__name__}"

    def fetch(self, *, cursor: Optional[str] = None, limit: int = 500, **kwargs) -> ConnectorResult:
        result = ConnectorResult(connector_type=self.connector_type, connector_version=self.connector_version)

        config_errors = self.validate_config()
        if config_errors:
            result.errors.append(ConnectorError(ErrorCategory.CONFIGURATION, "; ".join(config_errors)))
            return result

        url = self.config["url"]
        allow_local_dev = bool(self.config.get("allow_local_dev", False))
        timeout = float(self.config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        page_param = self.config.get("cursor_param", "cursor")

        params = dict(self.config.get("query_params", {}))
        if cursor:
            params[page_param] = cursor
        params["limit"] = min(limit, 500)

        safe_host = host_label(url)
        try:
            current_url = url
            for hop in range(4):  # initial request + up to 3 redirects (Section 4's MAX_REDIRECTS)
                validate_url(current_url, allow_local_dev=allow_local_dev)
                with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                    response = client.get(current_url, params=params if hop == 0 else None, headers=self._auth_headers())

                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        result.errors.append(ConnectorError(ErrorCategory.HTTP_ERROR, "redirect response had no Location header"))
                        return result
                    current_url = urljoin(current_url, location)
                    continue
                break
            else:
                result.errors.append(ConnectorError(ErrorCategory.HTTP_ERROR, "too many redirects"))
                return result

            if response.status_code != 200:
                result.errors.append(ConnectorError(ErrorCategory.HTTP_ERROR, f"endpoint at {safe_host} returned HTTP {response.status_code}"))
                return result

            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            if content_type not in ALLOWED_CONTENT_TYPES:
                result.errors.append(ConnectorError(ErrorCategory.UNSUPPORTED_CONTENT, f"unexpected content-type '{content_type}' from {safe_host}"))
                return result

            content_length = len(response.content)
            if content_length > MAX_RESPONSE_BYTES:
                result.errors.append(ConnectorError(ErrorCategory.SIZE_LIMIT, f"response from {safe_host} exceeded {MAX_RESPONSE_BYTES} bytes"))
                return result

            body = response.json()
        except httpx.TimeoutException:
            result.errors.append(ConnectorError(ErrorCategory.TIMEOUT, f"connection to {safe_host} timed out"))
            return result
        except httpx.HTTPError as exc:
            result.errors.append(ConnectorError(ErrorCategory.CONNECTION, f"connection to {safe_host} failed: {type(exc).__name__}"))
            return result
        except ConnectorConfigError as exc:
            # A redirect hop pointed somewhere unsafe -- Section 4's
            # "revalidate redirect destinations" requirement. This
            # MUST be checked before the bare `except ValueError` below
            # -- ConnectorConfigError is itself a ValueError subclass,
            # so if that clause came first it would silently swallow
            # every blocked-redirect case and mis-report it as an
            # "invalid JSON" content error instead of the security-
            # relevant UNSAFE_DESTINATION category.
            result.errors.append(ConnectorError(ErrorCategory.UNSAFE_DESTINATION, redact_credentials(str(exc))))
            return result
        except ValueError as exc:  # json decode error
            result.errors.append(ConnectorError(ErrorCategory.UNSUPPORTED_CONTENT, f"response from {safe_host} was not valid JSON: {exc}"))
            return result

        items = body.get("items", body) if isinstance(body, dict) else body
        if not isinstance(items, list):
            result.errors.append(ConnectorError(ErrorCategory.UNSUPPORTED_CONTENT, "expected a JSON array (or an object with an 'items' array)"))
            return result

        for item in items:
            if not isinstance(item, dict):
                continue
            result.records.append(RawRecord(payload=item, external_id=_str_or_none(item.get("external_id"))))

        result.cursor = body.get("next_cursor") if isinstance(body, dict) else None
        result.has_more = bool(result.cursor)
        return result


def _str_or_none(value) -> Optional[str]:
    return str(value) if value not in (None, "") else None
