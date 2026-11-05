# Evidence & Evidence Relationship Model

B/3D/11. Two new tables: `evidence_items`
(`app/models/evidence.py`) and `evidence_relationships`
(`app/models/evidence_relationship.py`). Read
`docs/architecture/INTELLIGENCE_FUSION_ARCHITECTURE.md` first for why
these are new tables rather than extensions of `Event`/`EventCorrelation`.

## `Evidence` -- a reference layer, never media storage

An `Evidence` row never fetches or stores the content it points at. It
carries exactly one of five possible references, chosen by
`evidence_type` (`app/models/evidence.py`'s `EVIDENCE_TYPES`):

| `evidence_type` | What it must carry | Enforced by |
|---|---|---|
| `observation` | `event_id` (a real `Event`) | `evidence_service.validate_evidence_payload()` + DB CHECK |
| `ingestion_record` | `raw_record_id` (a real `RawRecord`) | same |
| `sensor_observation` | `observation_id` (a real `Observation`) | same |
| `report` | `content` (free text) | same |
| `analyst_note` | `content` (free text) | same |
| `document` | `external_reference_uri` (a pointer, never fetched) | same |
| `media_reference` | `external_reference_uri` | same |

The DB-level guarantee is the `ck_evidence_items_has_a_real_reference`
CHECK constraint: `event_id IS NOT NULL OR raw_record_id IS NOT NULL OR
observation_id IS NOT NULL OR content IS NOT NULL OR
external_reference_uri IS NOT NULL`. `evidence_service.
validate_evidence_payload()` runs the SAME logic before the insert is
even attempted, so a bad request gets a readable 400
(`ValueError`-driven) instead of a raw `IntegrityError` -- see
`backend/tests/test_evidence_and_relationships.py::
test_evidence_with_no_real_reference_is_rejected`,
`test_analyst_note_requires_content`.

**Immutability**: a reference-backed evidence item (`observation`,
`ingestion_record`, `sensor_observation`) is never editable after
creation -- same stance as `RawRecord`. Only `report`/`analyst_note`'s
free-text fields (`title`/`summary`/`content`) can be updated via
`PATCH /evidence/{id}`, because those ARE the content, not a pointer to
it (`evidence_service.update_evidence_content()` raises if asked to set
`content` on anything else -- see
`test_only_free_text_fields_can_be_updated`).

## `EvidenceRelationship` -- vs. `EventCorrelation`

The module docstring in `evidence_relationship.py` states this
explicitly, and it's worth repeating here since it's the single most
important distinction:

| | `EventCorrelation` | `EvidenceRelationship` |
|---|---|---|
| Endpoints | event <-> event only | event<->event, event<->evidence, evidence<->evidence |
| Who creates it | only `correlation_service.recompute()` | `fusion_service` (rule_based) OR an analyst via `POST /relationships` (analyst_created); `model_assisted` is a reserved, documented, currently-unused value |
| Ordering | canonical `(event_a_id < event_b_id)` -- undirected | directional `source -> target` -- `supports`/`derived_from`/etc. have real meaning in one direction |
| Review vocabulary | `candidate` / `confirmed` / `rejected` | `candidate` / `confirmed` / `rejected` / `uncertain` |
| Undo | none | `reverse` -- puts it back to `candidate` without deleting anything, `is_reversed`/`last_reversed_at` record that it happened |

`RELATIONSHIP_TYPES`: `supports`, `contradicts`, `corroborates`,
`derived_from`, `duplicate_candidate`, `temporally_associated`,
`spatially_associated`, `shares_source_identifier`, `analyst_linked`.

`RELATIONSHIP_ORIGINS`: `rule_based` (written only by
`fusion_service.py`'s future candidate-generation extension points --
nothing in the fusion run actually writes an
`EvidenceRelationship`; it writes `EventCorrelation`/`Conflict` rows,
so every relationship that exists today came through the analyst API),
`model_assisted` (reserved, unused -- see
`docs/analytics/CONFIDENCE_AND_SOURCE_RELIABILITY.md`), `analyst_created`
(the only origin `POST /relationships` can ever produce -- enforced
server-side in `app/api/routes/relationships.py`, never
client-supplied).

Reference integrity: `source_event_id`/`source_evidence_id` and
`target_event_id`/`target_evidence_id` are each guarded by a CHECK
constraint requiring exactly one of the pair to be set
(`ck_evidence_relationships_one_source_ref`, `..._target_ref`), and
`relationship_service._resolve_ref()` confirms the referenced row
actually exists in this organization BEFORE insert, raising
`InvalidReferenceError` (-> 404) otherwise --
`test_relationship_to_a_nonexistent_record_is_rejected`. A self-link
(same type, same id, on both sides) is rejected --
`test_self_link_is_rejected`.

**Idempotent creation**: `create_relationship()` returns
`(relationship, created: bool)`; submitting an identical
(source, target, relationship_type) a second time returns the existing
row with `created=False` rather than erroring or duplicating --
`test_duplicate_relationship_submission_is_idempotent`. This mirrors
`assessment_service.link_evidence()`'s own idempotent-tuple pattern.

**An `analyst_created` relationship always has a human author**:
`created_by_user_id` is required whenever `origin="analyst_created"` --
`test_analyst_created_relationship_without_an_author_is_rejected`. A
`rule_based` relationship has no human author by construction --
`test_rule_based_relationship_requires_no_human_author`.

## The review workflow in one picture

```
candidate --review(confirmed|rejected|uncertain)--> {confirmed|rejected|uncertain}
{confirmed|rejected|uncertain} --reverse--> candidate (is_reversed=True, last_reversed_at set)
candidate --reverse--> ERROR (nothing to reverse)
```

Every transition writes to the SAME `AuditRecord` table the rest of the
platform already uses (`evidence_relationship.review` /
`evidence_relationship.reverse`), queryable per-relationship via
`relationship_service.get_review_history()` ->
`GET /relationships/{id}/history`. See
`docs/workflows/ANALYST_REVIEW_WORKFLOW.md` for the full workflow
documentation shared with `Conflict`.

## What this does NOT do

No evidence item ever stores the bytes of a document or image it
references -- `external_reference_uri` is a pointer this platform
never fetches (no SSRF surface here, unlike the `http_connector`).
No relationship can be created between two records in different
organizations -- every lookup is organization-scoped. No relationship
is ever silently auto-confirmed; `review_status` only ever changes
through an explicit `POST /relationships/{id}/review` call. No
relationship row is ever deleted -- `reverse` is the only "undo," and it
preserves full history.

## Tests

`backend/tests/test_evidence_and_relationships.py` (16 tests): Evidence
reference validation (all five types, missing-reference rejection,
free-text-only editability); relationship creation (valid pairs,
invalid references, self-link rejection, duplicate-submission
idempotency, event<->evidence pairing, origin/author rules); the
confirm/reject/uncertain/reverse workflow end to end including its
audit history shape; and API-level permission checks (`viewer` can read
but not create/review a relationship).
