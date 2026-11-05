# Human Review of Assessments

Decisions: `accepted`, `rejected`, `further_review_requested`. Reviewers may also
flag information as `insufficient_information` and/or `conflicting_information`.

* Requires `assessment:review` (Administrator, Analyst, Investigator). Viewers
  can read scores and history but not compute or decide.
* Notes are required. Changing the previous decision requires `change_reason`.
* Each decision is an append-only `AssessmentReview` row linked to the one it
  supersedes, and stores the advisory score/band that existed at that moment.
* The model-versus-human comparison maps band -> expected decision (high ->
  further review, low -> accept, medium -> none) **only to show disagreement**;
  the human decision always governs and nothing happens automatically.
* A decision does not change `Assessment.status`. Archived assessments cannot be
  reviewed. Reviews made on an older assessment version are labelled as such.
* Audit actions: `assessment.score`, `assessment.review`,
  `model_evaluation.run`, `model_evaluation.failed`.
