# Intelligence Fusion Architecture

the architectural map: what got reused unchanged from
the foundation and data platform, what got extended, and what is genuinely new. Read this first,
before any of the other docs -- they all assume the split
described here.

## The one rule this layer followed throughout

Section 3's instruction was explicit: **do not duplicate existing
entities** (`Event`, `EventCorrelation`, `Investigation`,
`correlation_service.py`). Every new model and service
exists because it represents a genuinely new concept had no
place for -- never a parallel, slightly-different version of something
that already existed.

## Reused, unchanged

| Thing | Stays exactly as left it |
|---|---|
| `Event` | The canonical observation. The fusion layer never adds columns to it, never mutates one, never merges two into one. |
| `EventCorrelation` `app/services/correlation_service.py` | Rule-based event<->event candidate detection, confirm/reject review only. The fusion layer adds exactly one new optional parameter to `recompute()` (`time_window_seconds_by_type` -- see `docs/analytics/TEMPORAL_CORRELATION.md`); everything else, including the module's own docstring's claims, is unchanged and still backed by the original tests (`backend/tests/test_correlation.py`, all still passing). |
| `Investigation` | Case management. Gained three new columns this layer (`purpose`, `scope`, `collaborator_user_ids`) because Section 20 of its own spec asked for them, but the model's core identity (status/priority/review workflow) is untouched. |
| `AuditRecord` / `app/services/audit_service.py` | The append-only audit log. The fusion layer adds one new read helper, `list_for_target()`, so relationship/conflict review history can be queried -- no new history table was built in parallel. |

## New, and why each one earns its own model

| Model | Why it isn't just a reuse of something above |
|---|---|
| `Evidence` (`app/models/evidence.py`) | `Event` is an observation; `Evidence` is a REFERENCE layer that can point at an Event, a RawRecord, an Observation, or carry free analyst text/an external URI. Nothing models "a report that cites three things." |
| `EvidenceRelationship` (`app/models/evidence_relationship.py`) | `EventCorrelation` is event<->event only, rule-based only, confirm/reject only. A relationship here can span event<->evidence or evidence<->evidence, can be hand-drawn by an analyst (`origin="analyst_created"`), supports a richer review vocabulary (`confirmed`/`rejected`/`uncertain`), and supports a non-destructive `reverse` action `EventCorrelation` has no equivalent for. See `docs/data/EVIDENCE_RELATIONSHIP_MODEL.md` for the full split. |
| `Conflict` (`app/models/conflict.py`) | Nothing represents "these two already-related things disagree." Deliberately scoped to pairs that already have an `EventCorrelation` row -- see `docs/analytics/CONFLICT_DETECTION.md`. |
| `Assessment` `AssessmentEvidenceLink` `AssessmentRevision` (`app/models/assessment.py`) | the `RiskAssessment` is a scored record tied to one subject. An `Assessment` here is a versioned, evidence-cited written judgment that can answer an open-ended question and change over time -- a different shape for a different job. See `docs/workflows/ASSESSMENT_LIFECYCLE.md`. |
| `FusionJob` (`app/models/fusion_job.py`) | Same spirit as the `IngestionJob` (a real, inspectable job record), but for a fusion run instead of an ingestion run -- no existing job table covers "correlation recompute + conflict detection, as one auditable unit." |

## Service layer map

```
app/services/
  identifier_service.py     -- namespaced identifier/attribute comparison (Section 7)
  evidence_service.py       -- Evidence CRUD + reference validation (Section 3B)
  relationship_service.py   -- EvidenceRelationship CRUD + review/reverse workflow (3D, 11)
  conflict_service.py       -- conflict detection over EXISTING correlations only (Section 9)
  assessment_service.py     -- Assessment CRUD + versioning + evidence linking (Section 12)
  fusion_service.py         -- orchestrates correlation_service.recompute() + conflict_service.detect_conflicts() as one FusionJob (Section 4)
  graph_service.py          -- bounded BFS evidence graph (Section 10)
```

`fusion_service.py` is the only module that calls both a original
service (`correlation_service`) and a original service
(`conflict_service`) -- this is the seam where "fusion" actually means
something: one explicit, authorized action that composes both
analytical passes and records the result as a single `FusionJob`, never
a background scheduler.

## Separation of five things that must never collapse into one score

Section 7/12's most important discipline, enforced across every model
above, not just documented once and forgotten:

1. **Data quality** (the data platform: `RawRecord.validation_status`, `quality_service.py`) -- is a record well-formed?
2. **Source reliability** (the data platform: `DataSource.reliability_weight`) -- how much does this platform trust this source, as a human-set number with a mandatory reason?
3. **Evidence support** (the fusion layer: `AssessmentEvidenceLink.role` = supporting/contradicting) -- what evidence backs or undercuts a specific written judgment?
4. **Analytical confidence** (the fusion layer: `Assessment.confidence_level`, qualitative low/moderate/high only) -- how sure is the analyst, in their own words?
5. **Severity** (core: `Event.source_severity` as reported, `Event.priority` as this platform's triage) -- how serious is the underlying observation?

See `docs/analytics/CONFIDENCE_AND_SOURCE_RELIABILITY.md` for the full
treatment and the explicit "what would collapsing these look like, and
why this codebase never does it" discussion.

## What this layer does NOT build

No probabilistic/ML scoring anywhere (`RELATIONSHIP_ORIGINS` includes
`model_assisted` as a documented placeholder value, but nothing in this
layer ever writes that value -- see
`docs/analytics/CONFIDENCE_AND_SOURCE_RELIABILITY.md`'s "what this does
NOT do"). No automatic merging of correlated or conflicting events --
every `Event` row that exists before a fusion run exists, unchanged,
after it. No scheduled/background fusion -- `POST /fusion/run` is the
only entry point, same discipline as the `/correlation/recompute`.
No cross-organization graph traversal or evidence linking -- every query
in every service filters by `organization_id` from the
authenticated token.

## Tests exercising the architecture itself

`backend/tests/test_fusion_and_graph.py`'s fusion_service tests confirm
the orchestration composes both passes correctly and records real
counts; its per-event-type window override test
(`test_per_event_type_time_window_override_is_actually_consumed`)
confirms the one change made to `correlation_service.py` this layer is
real and additive, not a silent behavior change to the existing
rules (the own `test_correlation.py` suite, unmodified, still
passes in full).
