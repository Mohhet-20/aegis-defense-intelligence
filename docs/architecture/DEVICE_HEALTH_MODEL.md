# Device Health-Finding Rule Engine (Section 4)

**Status: IMPLEMENTED, tested.** This document is the detailed companion
to `docs/architecture/FLEET_MANAGEMENT.md` Section 5 -- it covers
`app/services/fleet_health_service.py` rule by rule. See
`docs/operations/INFRASTRUCTURE_ALERTS.md` for how these same findings
drive the alert queue.

## 1. The three binding measurement-quality rules

Every rule in this module follows three rules stated verbatim in the
prompt and enforced structurally, not just by convention:

1. **Missing data stays missing.** A metric a device never reported
   (e.g. `resource_metrics` has no `battery_pct` key) produces **no
   finding** for that metric. `evaluate_health_findings()` only ever
   calls `_metric_finding()` when the corresponding key is present and
   not `None` (see the `if disk_pct is not None:` / `if battery_pct is
   not None:` / `if latest.queue_depth is not None:` guards) -- a
   missing metric is never fabricated as `0` or `100`.
2. **Stale vs. fresh are distinguished.** Every finding dict carries an
   `as_of` timestamp: for a presence finding, `device.last_seen_at`
   itself; for a resource-metric finding, `latest.reported_at` (the
   `DeviceHealthReport.reported_at` the metric actually came from). A
   caller can always tell whether a finding reflects data from five
   minutes ago or five hours ago -- the finding never implies "this is
   current" by omission.
3. **Device-reported vs. server-computed are distinguished.** Every
   finding carries a `source`: `"device_reported"` for a raw metric
   value the device itself sent (disk/battery percentage, queue
   depth), or `"server_computed"` for a finding the server derived
   that the device cannot know from its own vantage point (presence/
   staleness, which depends on the server's receipt-time clock, not
   the device's).

## 2. The current rules, with exact thresholds

All thresholds are `app.core.config.Settings` fields (`FLEET_*`), so an
operator can retune them without a code change. Every finding's
`evidence` dict includes both the observed value and the threshold(s)
it was compared against -- a finding is always independently checkable,
never just an opaque severity label.

| `rule_key` | Source | Severity logic | Default thresholds |
|---|---|---|---|
| `presence_offline` | `server_computed` | `critical` whenever `derive_presence_state()` returns `"offline"` | `FLEET_PRESENCE_OFFLINE_AFTER_SECONDS` = 600.0s since `last_seen_at` |
| `presence_stale` | `server_computed` | `warning` whenever `derive_presence_state()` returns `"stale"` (and *not* `"offline"` -- the two are mutually exclusive per evaluation) | `FLEET_PRESENCE_STALE_AFTER_SECONDS` = 120.0s since `last_seen_at` |
| `disk_usage_high` | `device_reported` (`resource_metrics.disk_used_pct`) | higher-is-worse: `critical` at `>= FLEET_HEALTH_DISK_CRITICAL_PCT`, `warning` at `>= FLEET_HEALTH_DISK_WARNING_PCT`, no finding below warning | warning 80.0%, critical 95.0% |
| `battery_low` | `device_reported` (`resource_metrics.battery_pct`) | lower-is-worse (`higher_is_worse=False`): `critical` at `<= FLEET_HEALTH_BATTERY_CRITICAL_PCT`, `warning` at `<= FLEET_HEALTH_BATTERY_WARNING_PCT`, no finding above warning | warning 20.0%, critical 5.0% |
| `sync_queue_backlog` | `device_reported` (`DeviceHealthReport.queue_depth`) | higher-is-worse, same shape as `disk_usage_high` | warning 500, critical 2000 |

No presence finding (`presence_offline` nor `presence_stale`) is
produced when the device is `"online"` or `"unknown"` -- a brand-new
device that has never reported at all produces no fabricated
`"offline"` finding; `"unknown"` and `"offline"` are genuinely
different findings (Rule 1 above), never conflated.

A device with **no health-report history at all** (`get_latest_health_report()`
returns `None`) still correctly produces its presence finding (if any)
and simply returns early with no resource-metric findings -- this
function never raises on a device with zero reported metrics.

## 3. The shared metric-finding helper

`_metric_finding(rule_key, value, *, warning, critical, label, as_of,
higher_is_worse=True)` is the one piece of comparison logic every
resource-metric rule shares -- `disk_usage_high`/`sync_queue_backlog`
call it with the default `higher_is_worse=True`, `battery_low` calls it
with `higher_is_worse=False`. This is deliberate: a new threshold-style
rule over a new metric reuses this helper rather than reimplementing
comparison logic, and every such rule's finding shape (`rule_key`,
`severity`, `source`, `as_of`, `evidence`, `explanation`) stays
identical across rules.

## 4. How to add a new rule

1. Decide which of the three measurement-quality rules (Section 1)
   govern it -- in practice, every new resource-metric rule should: (a)
   only fire when the metric is present and not `None`; (b) stamp
   `as_of` from the `DeviceHealthReport` the metric came from, never
   "now"; (c) mark `source="device_reported"` unless the server itself
   is deriving the value (in which case `"server_computed"`, and `as_of`
   should still be the data the derivation was computed from, not the
   evaluation time).
2. Add the new threshold(s) to `app.core.config.Settings` as
   `FLEET_HEALTH_<METRIC>_WARNING_*`/`FLEET_HEALTH_<METRIC>_CRITICAL_*`,
   with a safe default and a comment explaining the unit.
3. In `evaluate_health_findings()`, read the metric off
   `latest.resource_metrics` (or a new dedicated `DeviceHealthReport`
   column, if the metric doesn't belong in the free-form
   `resource_metrics` JSON blob) with an `is not None` guard, call
   `_metric_finding()` (or write new comparison logic only if the
   metric genuinely isn't a simple warning/critical threshold), and
   append the result to `findings` if it is not `None`.
4. If the new rule should also drive the alert queue, add a
   `(rule_key, alert_type)` pair to the loop in
   `fleet_alert_service.evaluate_alerts_for_device()` (reusing the
   existing `health_degraded`/`sync_backlog` `alert_type` values, or
   introducing a new one in `INFRA_ALERT_TYPES` if the condition is
   genuinely a new category) -- see
   `docs/operations/INFRASTRUCTURE_ALERTS.md` Section 2.
5. Write a test following the same three-part shape every existing
   rule test uses (see `tests/test_fleet_health_and_capabilities.py`):
   missing-metric produces no finding, below-warning produces no
   finding, warning/critical thresholds each produce the expected
   severity with the expected `evidence`/`as_of`/`source`.

## 5. What this module deliberately does not do

- It never collapses multiple findings into one aggregate "health
  score" -- every finding is returned as its own entry in the list,
  the same "never collapse genuinely separate concepts" discipline
  the four-signal sensor-health model established and Section 3
  of `docs/architecture/FLEET_MANAGEMENT.md` restates.
- It never phrases a finding as a threat, hostile-intent, or
  equipment-fault *determination* -- every `explanation` string is a
  plain statement of a measured value against a configured threshold
  ("Disk used is 97.0 (warning >= 80.0, critical >= 95.0)"), for a
  human operator to interpret, never a confirmed judgment.
- It is a pure, synchronous, request-scoped function -- there is no
  background job that periodically re-evaluates every device's health;
  findings are only ever computed on demand (a device-detail read) or
  inline during health-report ingestion (feeding the alert queue).
