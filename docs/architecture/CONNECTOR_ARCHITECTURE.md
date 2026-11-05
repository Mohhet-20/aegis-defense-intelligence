# Connector Architecture

How a source actually gets records into the ingestion
pipeline, and how a future sensor/CV/edge adapter plugs in without rewriting
the ingestion engine.

## The contract (`app/connectors/`)

Every connector -- file-based today, HTTP/synthetic also today, a real
sensor/CV/edge adapter in later work -- implements the same small
interface, `app.connectors.base.BaseConnector`:

```python
class BaseConnector(ABC):
    connector_type: str       # stable machine name, recorded on every RawRecord
    connector_version: str    # bumped when output shape/behavior changes

    def __init__(self, config: dict | None = None): ...
    def validate_config(self) -> list[str]: ...          # [] == valid
    def check_connectivity(self) -> tuple[bool, str | None]: ...  # best-effort probe
    def fetch(self, *, cursor=None, limit=500, **kwargs) -> ConnectorResult: ...
    def close(self) -> None: ...
```

`app.connectors.ingestion_service` (the engine, not a connector) only ever
talks to a connector through these four methods. It never reaches into a
connector's internals, and a connector never touches the database, never
normalizes, and never deduplicates -- that is `normalization_service.py`,
`validation_service.py`, and `ingestion_service.py`'s job, the SAME engine
regardless of which connector produced the records.

## Typed contracts (`app/connectors/types.py`)

- `RawRecord(payload: dict, external_id: str | None, source_observed_at_raw: str | None)`
  -- one record exactly as the connector read it, before normalization.
- `ConnectorResult(connector_type, connector_version, records, errors, cursor, has_more, fetched_at)`
  -- what `fetch()` returns. `fetched_at` is always UTC-aware.
- `ErrorCategory` -- configuration / validation / connection / timeout /
  http_error / unsupported_content / size_limit / unsafe_destination / unknown.
  `RETRYABLE_CATEGORIES = {CONNECTION, TIMEOUT}` -- everything else (a 4xx,
  a validation failure, an SSRF block) is never auto-retried.
- `ConnectorError(category, message)` -- a connector-level failure (a
  malformed row, an unreachable host) that didn't even produce a record to
  validate. Reported to the caller the same way a per-record validation
  failure is: counted as rejected, never silently dropped.
- `ConnectorConfigError(ValueError)` -- raised only for a configuration
  problem (an unsafe URL, a bad auth_env_var type), carrying an
  `ErrorCategory`. **Caught explicitly before the generic `except ValueError`**
  wherever it's handled (see the SSRF note below) -- it is itself a
  `ValueError` subclass, so getting the except-clause order wrong silently
  mis-reports a blocked SSRF attempt as an "invalid JSON" content error.

## Implemented connectors

| Type | File | Config | Notes |
|---|---|---|---|
| `json_file` | `json_connector.py` | none (takes `content: bytes`) | one-shot file upload |
| `csv_file` | `csv_connector.py` | none (takes `content: bytes`) | one-shot file upload |
| `synthetic_demo` (+ legacy alias `synthetic_generator`) | `synthetic_connector.py` | `count` (1-500), `seed` | deterministic: same seed -> same batch, always |
| `http_api` | `http_connector.py` | `url`, `timeout_seconds`, `auth_env_var`, `allow_local_dev`, `cursor_param`, `query_params` | real HTTP connector, SSRF-hardened (below) |

File connectors (`json_file`, `csv_file`) are selected by the **uploaded
file's extension**, not by the source's `source_type` -- a single
`file_upload`-mode source can receive either. Connector-driven sources
(`http_api`, `synthetic_demo`) are selected by `source_type` and are "run"
explicitly via `POST /api/v1/sources/{id}/run`, never automatically.
`app.connectors.registry.is_connector_driven(source_type)` is the one place
that distinguishes the two.

## The HTTP connector's safety requirements (Section 4)

Every one of these is implemented, not aspirational -- see
`app/connectors/url_safety.py` and `tests/test_connectors.py`:

- **Scheme allowlist**: `https` only by default. `http` is permitted ONLY
  when `config.allow_local_dev=True` AND the resolved host is loopback.
- **No credentials in the URL**: `user:pass@host` is rejected outright.
- **DNS resolution + IP-range check**: every hostname is resolved via
  `socket.getaddrinfo`, and every resolved address is checked against
  `ipaddress`'s `is_loopback` / `is_private` / `is_link_local` (covers the
  `169.254.169.254` cloud-metadata address) / `is_reserved` / `is_multicast`
  / `is_unspecified`. **Link-local, private, reserved, and multicast are
  blocked unconditionally** -- `allow_local_dev=True` only ever excepts
  loopback, never metadata or private ranges. Verified by
  `test_validate_url_blocks_cloud_metadata_even_with_allow_local_dev`.
- **Redirect revalidation**: every hop (up to `MAX_REDIRECTS = 3`, so 4
  requests total) is re-validated through `validate_url()` before it is
  followed -- a redirect to an unsafe destination is caught and reported as
  `ErrorCategory.UNSAFE_DESTINATION`, never silently followed.
- **Bounded response size** (`MAX_RESPONSE_BYTES`, same bound as a file
  upload) and **content-type allowlist** (`application/json` only).
- **Timeouts**: `DEFAULT_TIMEOUT_SECONDS = 10.0`, configurable up to 60s.
- **No credentials in logs**: `redact_credentials()` / `host_label()` strip
  anything sensitive before a URL ever reaches an error message or log line.
- **TLS verification is never disabled** -- there is no code path that sets
  `verify=False` or equivalent.
- **Credentials from environment only**: `config.auth_env_var` names an
  environment variable; the literal token is never stored in
  `config_metadata` and never logged. If the named variable isn't set, the
  request simply goes out unauthenticated rather than failing validation --
  a source can be registered before its secret is provisioned.

**No real external endpoint is connected in this build.** The HTTP connector
is tested against a local `http.server` bound to `127.0.0.1`
(`tests/test_connectors.py`'s `mock_json_server` / `mock_server_factory`
fixtures) -- this is deliberate, not a placeholder: it proves the connector's
request/response/pagination/redirect/size/content-type handling works
end-to-end without requiring (or faking) a live third-party integration.
Connecting a real external source is an operational configuration step
(register a source with a real `url`), not a code change.

## Adding a future connector (sensor / CV / edge adapter)

1. Subclass `BaseConnector`, implement `validate_config()` and `fetch()`.
2. Add it to `app/connectors/registry.py`'s `_CONNECTOR_CLASSES` (if it's
   connector-driven) or `_FILE_CONNECTOR_CLASSES` (if it's a one-shot
   upload format).
3. That's it. `ingestion_service.run_connector_source()` and
   `_process_batch()` are already generic over any `ConnectorResult` --
   nothing in the ingestion engine, normalization, validation, dedup, or
   provenance layers needs to change.

## What this is NOT

A general-purpose server-side fetch proxy. `http_api` connectors only ever
request the one `url` a source is explicitly configured with; there is no
endpoint that takes a client-supplied URL and fetches it on the server's
behalf outside this connector's own SSRF-hardened path.
