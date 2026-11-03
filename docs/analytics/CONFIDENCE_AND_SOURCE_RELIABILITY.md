# Confidence & Source Reliability (Phase 3 extension)

Phase 3, Sections 7/12. Extends Phase 2's
`docs/analytics/SOURCE_RELIABILITY.md`, which already keeps six
concepts deliberately separate (source reliability, record quality,
analytical confidence, event severity, assessment priority, correlation
match strength). Read that document first. This one adds the two new
concepts Phase 3 introduces and closes the loop on that document's own
forward-reference to "Phase 3's multisource fusion."

## The two new concepts

| Concept | What it measures | Where it lives | Who sets it |
|---|---|---|---|
| **Evidence support** | Whether a specific piece of evidence backs or undercuts a specific written `Assessment` | `AssessmentEvidenceLink.role` (`supporting` / `contradicting`) | An analyst, via `POST /assessments/{id}/evidence` -- never inferred from the evidence's content |
| **Assessment confidence** | How sure the AUTHOR of a written assessment is in their own conclusion | `Assessment.confidence_level` (`low` / `moderate` / `high`, qualitative only) + `confidence_rationale` (free text) | The assessment's author, stated directly -- `assessment_service.py` never computes this value from anything |

## Why `confidence_level` is a 3-value enum, never a float

Phase 1's `RiskAssessment.confidence` (unchanged) is already a nullable
float, set "only when there's a real basis" -- but it's tied to one
scored subject. An `Assessment` here answers an open-ended analytical
question, often without a clean numeric basis at all. Rather than
invent a fabricated-looking float for a judgment that has no real
statistical grounding, `CONFIDENCE_LEVELS = ("low", "moderate", "high")`
is the entire vocabulary (`app/models/assessment.py`), and
`confidence_rationale` is required to be meaningful alongside it --
the model layer has no code path that computes a confidence level; it
only validates that a submitted value is one of the three allowed
strings (`assessment_service.create_assessment()`/`update_assessment()`,
tested by `test_invalid_confidence_level_is_rejected`).

## `RELATIONSHIP_ORIGINS` includes `model_assisted` -- and nothing produces it

`app/models/evidence_relationship.py`'s `RELATIONSHIP_ORIGINS =
("rule_based", "model_assisted", "analyst_created")` reserves a third
value for a future scored/ML-assisted relationship generator. **Nothing
in this phase writes that value.** `fusion_service.py`'s own candidate
generation writes `EventCorrelation`/`Conflict` rows (both Phase-2/
Phase-3 deterministic, rule-based structures with no ML component),
and the only two places `EvidenceRelationship` rows are created are
`relationship_service.create_relationship()` (always `analyst_created`
when called through `POST /relationships` -- enforced server-side in
the route, never client-supplied) and whatever future
`fusion_service.py` extension would write `rule_based` relationships
directly (not built in this phase either). `model_assisted` exists in
code today purely as a documented, validated, UNUSED enum member --
the honest way to reserve a shape for later without pretending a
model-assisted generator exists.

## Closing the loop on Phase 2's forward-reference

`docs/analytics/SOURCE_RELIABILITY.md` ends with: "An automated
source-scoring model that adjusts reliability from outcome history is
explicitly a later-phase feature (the kind of thing Phase 3's
multisource fusion ... would own)." Phase 3 is that phase, and this is
the explicit confirmation: **no automated source-scoring was built.**
`DataSource.reliability_weight` is unchanged -- still a human-set
number with a mandatory documented reason
(`source_service.set_reliability_weight()`, untouched this phase). The
fusion pipeline (`fusion_service.py`) never reads or writes
`reliability_weight`, and no new field anywhere derives a source's
trustworthiness from how often its events survive correlation, conflict
resolution, or assessment citation. That remains reserved for a later
phase (most likely Phase 10's explainable-AI/risk-analytics work, or a
dedicated MLOps phase), not silently absorbed into this phase's scope.

## The full, now-eight-concept table

Extending Phase 2's six with this phase's two:

1. Source reliability (`DataSource.reliability_weight`) -- unchanged.
2. Record completeness/validation quality (`RawRecord.validation_status`) -- unchanged.
3. Analytical confidence, event-level (`Event.confidence`) -- unchanged.
4. Event severity, as reported (`Event.source_severity`) -- unchanged.
5. Assessment/triage priority (`Event.priority`) -- unchanged.
6. Correlation match strength (`EventCorrelation.match_strength`) -- unchanged.
7. **Evidence support** (`AssessmentEvidenceLink.role`) -- new this phase.
8. **Assessment confidence** (`Assessment.confidence_level` + `confidence_rationale`) -- new this phase.

None of these eight is ever derived from another, and none is ever
collapsed into a single composite score anywhere in this codebase.

## What this does NOT do

No model ever runs anywhere in this phase's fusion/evidence/assessment
code -- `model_assisted` is reserved vocabulary, not a working feature.
No automated source reliability scoring. No numeric confidence
("87% confidence") anywhere in an `Assessment` -- only the three
qualitative levels, always paired with a human-written rationale. No
evidence-support role beyond `supporting`/`contradicting` -- there is no
"neutral" or "weak support" gradient in this phase.

## Tests

`backend/tests/test_assessments.py::test_invalid_confidence_level_is_rejected`,
`test_evidence_traceability_supporting_and_contradicting`,
`test_information_gaps_and_assumptions_are_stored_as_stated` (confirms
assumptions/gaps are recorded verbatim, never auto-generated).
`backend/tests/test_evidence_and_relationships.py::
test_rule_based_relationship_requires_no_human_author` and
`test_analyst_created_relationship_without_an_author_is_rejected`
together confirm the origin/authorship split that keeps
`model_assisted` honestly unused.
