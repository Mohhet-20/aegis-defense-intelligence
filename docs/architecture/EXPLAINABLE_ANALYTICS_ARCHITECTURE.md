# Explainable Analytics Architecture

Adds an explainable, reviewable analytics layer **on top of** the
Records. It does not replace the model registry, evidence system,
assessment model or audit log; it reads and extends them.

## Implementation plan that was followed (based on the inspected repository)

| Need | Existing component found | Decision |
|---|---|---|
| Model registry | `ModelRecord` | Reused unchanged. Evaluations reference it by id and record the version. |
| Model outputs | `DetectionResult` (P4), `RiskAssessment` (P1) | Reused. A **read-only** normalizer maps them to one shared schema; nothing is copied to a new table. |
| Evaluation | `ModelEvaluationRun` (P4, detection), `TrackingEvaluationRun` (P5) | Reused and surfaced in the overview. New `ClassificationEvaluationRun` added for classification/probability metrics, which had no home. |
| Assessments, versions | `Assessment`, `AssessmentRevision`, `AssessmentEvidenceLink` (P3) | Reused unchanged (no column added to `assessments`). |
| Audit | `audit_service.record` | Reused for every scoring, review and evaluation action. |
| Auth / RBAC | `Permission` / `ROLE_PERMISSIONS` | Three permissions added. |

## What was added

* **Pure analytics package** `app/analytics/` (no DB, no network): `metrics.py`,
  `explainers.py`, `scoring.py`.
* **Three append-only tables** (one migration, `75b9cd8a733e`):
  `classification_evaluation_runs`, `assessment_score_snapshots`,
  `assessment_reviews`.
* **Services:** `model_output_service`, `explanation_service`,
  `classification_evaluation_service`, `assessment_scoring_service`,
  `assessment_review_service`.
* **Routes:** `/model-outputs`, `/model-evaluations`, and score/review routes
  under `/assessments/{id}` (see `docs/api/ANALYTICS_API.md`).
* **Frontend:** evaluation dashboard + detail, model-outputs list + detail with
  an explanation panel, and an advisory-score / human-review panel embedded in
  the existing assessment detail page.

## Design principles (all enforced in code and tests)

1. **Never manufacture** a confidence, explanation, or metric. Missing stays
   missing (`null` + reason).
2. **Distinct concepts stay distinct.** Model confidence, evidence quality,
   source reliability, uncertainty, and assessment priority are separate fields
   of a score snapshot; they are never blended into one number.
3. **Advisory only.** Scores rank human review attention. They are not threat
   scores, never use identity/appearance/protected attributes (the rule's
   inputs are a closed list), and never trigger an action. Recording a review
   decision does not change `Assessment.status`.
4. **Append-only history.** Re-scoring and re-reviewing add rows; earlier rows
   are never edited. A changed decision requires a stated reason.
5. **Honest failure.** Bad input persists nothing; an unexpected internal
   failure persists a `failed` run with no results.
6. **Org isolation.** Every query is filtered by the caller's organization;
   cross-org access returns 404.
