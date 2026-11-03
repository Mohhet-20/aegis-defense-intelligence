# Source Reliability, Evidence Quality, and Confidence

Phase 2, Section 16. These are deliberately kept as SIX separate
concepts in this codebase. Collapsing any two of them into one number is
exactly the mistake this document exists to prevent.

| Concept | What it measures | Where it lives | Who sets it |
|---|---|---|---|
| **Source reliability** | How much this organization has decided to trust a *source*, as a configured assumption | `DataSource.reliability_weight` (0.0-1.0) | An authorized admin/analyst, via `PUT /api/v1/sources/{id}/reliability`, **with a required documented reason** |
| **Record completeness / validation quality** | Did a specific raw record parse cleanly -- required fields present, timestamp/coordinate valid | `RawRecord.validation_status/_errors/_warnings` | Computed automatically by `validation_service.py` -- never set by a human |
| **Analytical confidence** | Whether there's a real basis to estimate how sure we are about a specific *event* | `Event.confidence` | Only set when a real basis exists; `None` otherwise -- never fabricated |
| **Event severity** | What the source itself said about how severe its own report is | `Event.source_severity` | Verbatim from the source, never altered |
| **Assessment priority** | This platform's own triage value, derived from severity via a documented mapping | `Event.priority` | `normalization_service.map_severity_to_priority()` -- deterministic, documented, never silently escalated for an unrecognized label |
| **Correlation match strength** | How many independent correlation signals fired for a candidate pair, bounded 0-1 | `EventCorrelation.match_strength` | `correlation_service.py`, a documented weighted sum -- never a probability of truth |

## The rule this document exists to enforce

**None of the above is ever converted directly into a truth claim about
the underlying real-world event, and none of them is ever auto-derived
from another.** Concretely:

- A high-reliability source reporting something does not make that
  report "true" -- it is still one observation, stored with its own
  provenance, subject to the same validation/dedup/correlation pipeline
  as any other.
- Reliability weight is **never recomputed automatically** from
  correlation counts, duplicate counts, or how often a source's events
  get confirmed in investigations. It only ever changes when an
  authorized person explicitly sets it, and `source_service.set_reliability_weight()`
  refuses the call outright if no `reason` is supplied
  (`ValueError: a documented reason is required...`) -- enforced
  server-side, not just a UI convention. Every change is audit-logged
  (`source.reliability_change`) with the new weight and the stated reason.
- Two correlated events are never treated as "independent corroboration"
  if they share a source (see `EVENT_CORRELATION.md`'s weighting) --
  repeated observation from the SAME origin is structurally weaker
  evidence than two different origins agreeing, and the weighting
  reflects that.
- A duplicate is never promoted into stronger evidence by virtue of being
  uploaded multiple times -- deduplication (`DEDUPLICATION_POLICY.md`)
  exists precisely to prevent a repeated report from silently counting as
  multiple observations.

## What's exposed to whom

Reliability weight and source operational metadata (`enabled`,
`last_error_category`, `connection_mode`) are visible to any role with
`SOURCE_READ`. Raw-record-level validation detail is gated by the
separate `RAW_RECORD_READ` permission (`DATA_PROVENANCE.md`). Data-quality
summaries (`quality_service.py`) are visible to every authenticated role
(`DATA_QUALITY_READ`) -- they describe pipeline health, not evidentiary
weight, so there's no reason to restrict them further.

## What this phase does NOT build

An automated source-scoring model that adjusts reliability from outcome
history is explicitly a later-phase feature (the kind of thing Phase 3's
multisource fusion or a later AI-analytics phase would own) -- nothing
here pretends one exists. `reliability_weight` today is exactly what it
says: a number a human configured, with a reason on file for why.
