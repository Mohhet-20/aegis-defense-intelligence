# Data Classification and Handling (Phase 14)

This is a handling scheme for AEGIS data. It is **documentation plus a small number of enforced controls**. Only
`Evidence.access_classification` (default `internal`) exists as a stored classification field; no other table carries
a classification column, and classification is not used to drive a global access policy. Access is enforced by
RBAC permissions and organization isolation, not by labels.

No legal or regulatory compliance (GDPR, ISO 27001, SOC 2, export-control regimes, etc.) is claimed. Mapping these
controls to a specific regime remains outstanding work.

| Class | Examples | Handling | Controls actually in place |
|---|---|---|---|
| public | Static docs, health liveness (`/health`) | No restriction | Health returns no config or secrets |
| internal | Sensor metadata, model registry, scenario definitions, job status | Authenticated, org-scoped, permission-gated | RBAC + org scoping on every route (see ORGANIZATION_ISOLATION.md) |
| confidential | Investigations, evidence, assessments, events, copilot conversations | Org-scoped; reads and writes need explicit permission; changes audited | Permissions, audit events, foreign-reference checks, lifecycle protection (not deletable via lifecycle API) |
| sensitive_source | Private media, raw ingested records, uploaded files | Private store, no static serving, download only through authorized endpoint | Content-hash verified on download, `media.content_access` audited, `Cache-Control: no-store`, bounded uploads |
| secret | `SECRET_KEY`, password hashes, device credentials, connector secrets | Never returned by APIs, never logged, never shown in UI | `/security/config` reports only booleans for secrets; audit redaction; failed-login audit stores a SHA-256 prefix + length, not the identifier |

## Log and audit minimisation
- Audit metadata is passed through `audit_service.redact` (passwords, tokens, keys, secrets are masked).
- `authz.denied` events store permission, role, method and a path with id-like segments masked; never the body.
- Application logs and audit records are separate; request ids are sanitised.

## Exports and downloads
Exports require their own permission (export is separate from read). Media content access is audited. Evidence-level
`access_classification` is stored and returned but is **not** currently used to filter listings or exports.

## External model providers
External providers are used only when explicitly configured through the existing copilot/provider settings
(see COPILOT_PRIVACY.md). Nothing in Phase 14 enables a provider by default.

## Remaining work
- Use classification labels to drive policy (filter, export, retention) beyond `Evidence`.
- Field-level or at-rest encryption is **not implemented**.
- Compliance mapping and DPIA-style review.
