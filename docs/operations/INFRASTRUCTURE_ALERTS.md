# Infrastructure Alerts (Phase 9, Section 9)

**Status: IMPLEMENTED, tested.** See `app/models/infrastructure_alert.py`
and `app/services/fleet_alert_service.py`.

## 1. This is fleet-health alerting, never intelligence/threat alerting

`InfrastructureAlert` is a dedicated model/queue, deliberately
**separate** from intelligence `Event`s, `ObservationAnomaly` candidates,
and `RiskAssessment`/threat records -- the same deliberate separation
Phase 8 drew between `SyncConflict` (a sync-protocol concern) and
Phase 3's `Conflict` (an event-fusion concern). Every alert this queue
can ever hold is about **the health of the fleet itself** -- a device
went offline or stale, a resource metric crossed a threshold, a
device's configuration drifted from its assigned baseline -- **never**
about a sensed real-world condition. The two concerns never share a
table, a service, a review queue, or a permission (`INFRA_ALERT_*` is
entirely separate from `ANOMALY_*`/`RISK_*`).

**No real external notification is sent by this system.** No email,
SMS, or any other outbound channel is wired up anywhere in this
project -- alerts surface only through the API/UI (the Fleet
Operations Center's Alert Center) and the audit trail. This is
deliberate, not an oversight: nothing in this project has a configured
notification provider, and the phase's own instruction is that no
real external notification should exist unless one is already properly
configured (none is).

## 2. Every alert_type

`INFRA_ALERT_TYPES` (`app/models/infrastructure_alert.py`):

| `alert_type` | Raised from | Severity | `dedup_key` pattern |
|---|---|---|---|
| `device_offline` | `fleet_health_service`'s `presence_offline` finding | `critical` (matches the finding's own severity) | `device_offline:{device_id}` |
| `device_stale` | `fleet_health_service`'s `presence_stale` finding | `warning` | `device_stale:{device_id}` |
| `health_degraded` | `disk_usage_high` or `battery_low` findings | `warning` or `critical`, following the finding's own threshold logic (see `docs/architecture/DEVICE_HEALTH_MODEL.md`) | `disk_usage_high:{device_id}` or `battery_low:{device_id}` |
| `sync_backlog` | `sync_queue_backlog` finding | `warning` or `critical` | `sync_queue_backlog:{device_id}` |
| `config_drift` | `fleet_config_service.compute_drift()` returning `evaluated=True, has_drift=True` | always `warning` | `config_drift:{device_id}` |
| `capability_unhealthy` | reserved in `INFRA_ALERT_TYPES` | -- | -- |

**Honest note on `capability_unhealthy`:** this value is defined in
`INFRA_ALERT_TYPES` (reserving the vocabulary, the same pattern Phase
3 used for `RELATIONSHIP_ORIGINS`'s unused `model_assisted` value) but
`fleet_alert_service.evaluate_alerts_for_device()` does not currently
raise it -- capability health is surfaced today only through the
per-device/fleet-wide capability views (Section 4 of
`docs/architecture/FLEET_MANAGEMENT.md`), not yet through the alert
queue. A reasonable, explicitly-flagged follow-up, not a silent gap.

## 3. The `dedup_key` scheme, with concrete examples

Deduplication is enforced in the **service layer**, not by a database
unique constraint (see `app/models/infrastructure_alert.py`'s module
docstring for why a DB-level uniqueness on `dedup_key` alone would be
wrong: it would make it impossible to ever record a second,
genuinely-distinct occurrence of the same condition after the first
was resolved).

`dedup_key` is a stable identifier for "this ongoing condition,"
independent of severity escalation -- it never changes as a finding's
severity moves from `warning` to `critical`. Concrete examples:

- `device_offline:3f9a1c20-...` identifies "device `3f9a1c20-...` is
  offline" as one ongoing condition, regardless of how many times the
  rule re-fires.
- `disk_usage_high:3f9a1c20-...` identifies "device `3f9a1c20-...`'s
  disk usage is elevated" -- if the device's disk usage climbs from 82%
  (`warning`) to 97% (`critical`) across two health reports, both
  updates hit the **same** open alert row (its `severity` field is
  updated in place to `critical`, `occurrence_count` increments,
  `last_evaluated_at` advances) -- never two separate rows.
- `config_drift:3f9a1c20-...` identifies "device `3f9a1c20-...`'s
  config has drifted from its baseline" -- if the drift is first
  detected, then the device's config is fixed, then it drifts again a
  week later, the second drift creates a **brand-new** row (because the
  first was `resolved` in between) -- the alert history shows two
  distinct occurrences, not one row silently reused across a gap in
  which the condition was genuinely absent.

`_upsert_open_alert()` looks up the current open-like
(`open`/`acknowledged`/`reopened`) row for the same
`(organization_id, dedup_key)` before creating a new one; if found, it
updates `severity`/`evidence`/`explanation`/`occurrence_count`/
`last_evaluated_at` in place rather than inserting a duplicate.
`_auto_resolve_if_open()` does the mirror operation: when a condition
that *was* open is no longer observed on the next evaluation, the
existing open alert is automatically transitioned to `resolved` with a
`resolution_note` explaining why (e.g. `"device is online again"`,
`"metric is back within the normal range"`,
`"configuration matches the assigned baseline again"`) -- this is the
one case an alert transitions without a human action, and it is always
accompanied by an explanatory note, never a silent status flip.

**One deliberate exception:** when a device's `config_baseline_id` is
missing or its baseline was deleted (`drift.evaluated == False`), an
*existing* open `config_drift` alert is deliberately left untouched
rather than auto-resolved -- `drift["evaluated"] is False` is not
evidence of "no drift," so auto-resolving on it would be wrong (see
`docs/architecture/FLEET_MANAGEMENT.md`'s "missing baseline is never
no drift" rule, restated here for the alert queue specifically).

**Escalation and de-escalation between `device_offline`/`device_stale`:**
these two alert types are explicitly coordinated, not independent --
when a device becomes `offline`, its `device_stale` alert (if any) is
auto-resolved with the note `"superseded -- escalated to offline"`, and
the reverse (`stale` recovering from a prior `offline`) auto-resolves
the `device_offline` alert with `"device is reporting again (recovered
to stale, not yet fully online)"`. A device returning fully to `online`
auto-resolves both, each with `"device is online again"`.

## 4. The open/acknowledged/resolved/reopened lifecycle

`INFRA_ALERT_STATUSES = ("open", "acknowledged", "resolved", "reopened")`.

```
open --acknowledge--> acknowledged --resolve--> resolved --reopen--> reopened --resolve--> resolved
open --resolve-------------------------------------------> resolved
reopened --acknowledge--> acknowledged (also legal)
```

- `open` -- the initial state when a condition is first detected.
- `acknowledge` (`fleet_alert_service.acknowledge_alert()`) -- legal
  from `open` or `reopened` only. Stamps `acknowledged_at`/
  `acknowledged_by_user_id`.
- `resolve` (`resolve_alert()`) -- legal from `open`, `acknowledged`,
  or `reopened`. Stamps `resolved_at`/`resolved_by_user_id`/
  `resolution_note`. This is also how the system itself auto-resolves
  a condition that is no longer observed (Section 3), the one case
  this transition happens without a human actor -- a human-initiated
  resolve always carries a real `actor_user_id` and optional `note`
  from the request payload.
- `reopen` (`reopen_alert()`) -- legal **only** from `resolved`. This
  models a human explicitly disagreeing with a resolution (including an
  auto-resolution), or the same underlying condition recurring before
  the next automatic evaluation would have caught it. Never performed
  automatically.

Every transition (acknowledge/resolve/reopen) is fully audited
(`audit_service.record()`, actions `fleet.alert_acknowledge`/
`fleet.alert_resolve`/`fleet.alert_reopen`, each carrying the actor,
timestamp, and optional note) -- an illegal transition
(`InvalidAlertTransitionError`) raises rather than being silently
allowed, surfaced over the API as `400 Bad Request`.

**Permissions (who can do what):**

| Permission | Granted to | Covers |
|---|---|---|
| `INFRA_ALERT_READ` | Administrator, Analyst, Investigator, Viewer | `GET /fleet/alerts`, `GET /fleet/alerts/{id}` |
| `INFRA_ALERT_MANAGE` | Administrator, Analyst **only** | `POST /fleet/alerts/{id}/acknowledge`, `/resolve`, `/reopen` |

Deliberately **not** extended to Investigator -- unlike
`EDGE_CONFLICT_MANAGE` (Phase 8), which Investigator *does* hold
because resolving a sync conflict is case-work over intelligence data,
acknowledging/resolving a fleet-health alert is **fleet operations**,
kept analyst/admin-only the same way `DEVICE_MANAGE`/`FLEET_SITE_MANAGE`
are. Viewer and Investigator both get read-only fleet awareness
(`INFRA_ALERT_READ`) but cannot act on an alert.

## 5. Known gaps

- `capability_unhealthy` is a reserved alert_type with no current
  evaluator (Section 2).
- No real external notification channel exists or is configured
  (Section 1) -- surfacing is API/UI/audit-trail only.
- Inline alert (re-)evaluation during health-report ingestion still
  only runs when a device successfully submits a report -- a device
  that only ever sends bare heartbeats (never a full health report)
  will not get a `device_offline`/`device_stale` alert raised or
  auto-resolved purely from heartbeat traffic through that inline
  path. This is now covered regardless of heartbeat/health-report
  traffic by the explicit `POST /fleet/alerts/evaluate-sweep` sweep
  (see `docs/architecture/FLEET_MANAGEMENT.md` Section 7), which an
  operator or external cron can trigger to re-evaluate every device's
  presence/health/drift state at once.
