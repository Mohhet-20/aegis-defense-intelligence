# Assessment Review-Priority Scoring (Phase 10)

Rule `review_priority_v1` (version `1`), `app/analytics/scoring.py`.

**Meaning:** an advisory ranking of how much *human review attention* an
assessment deserves. Scale: 0-100 review-priority points, uncalibrated; not a
probability and not a threat level. Bands: `high` >= 50, `medium` >= 25, else
`low`.

## Inputs (closed list)

`contradicting_evidence_count`, `unresolved_conflict_count`,
`information_gap_count`, `supporting_evidence_count`,
`analyst_confidence_level`. Nothing about identity, appearance, protected
characteristics or a lone statistical anomaly is, or can become, an input.

## Default points

| Factor | Points | Cap |
|---|---|---|
| contradicting evidence | 10 each | 30 |
| unresolved conflicts among cited events | 12 each | 36 |
| stated information gaps | 4 each | 16 |
| no supporting evidence linked | 15 if zero | 15 |
| analyst confidence | low 10 / moderate 4 / high 0 / unstated 6 | 10 |

The score is the sum of the factor points shown (ceiling 100). Overrides are
allowed per key (numbers 0-50, validated, stored in the snapshot so any score is
reproducible). Unknown rules/keys return HTTP 422.

## Reported beside the score, never blended into it

* **model confidence** - only from cited detections, else "not available"
* **evidence quality** - counts (e.g. items with an integrity hash)
* **source reliability** - min/mean of the human-set `reliability_weight`
* **uncertainty** - listed indicators (stated confidence, gaps, conflicts)
* data-quality limitations, conflicts, and missing information

## Persistence

Each computation appends an `AssessmentScoreSnapshot` bound to the assessment
version; a snapshot is never edited. The UI warns when the latest score is for an
older version.
