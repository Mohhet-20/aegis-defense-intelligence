"""Advisory review-priority scoring for an assessment (Phase 10,
Section 5). Gathers what the assessment actually cites, applies a
documented rule from app/analytics/scoring.py, and appends an immutable
AssessmentScoreSnapshot. Model confidence, evidence quality, source
reliability and uncertainty are reported beside the score as separate
facts -- never folded into it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.analytics import scoring
from app.models.assessment import Assessment
from app.models.assessment_score import AssessmentScoreSnapshot
from app.models.conflict import Conflict
from app.models.data_source import DataSource
from app.models.detection_result import DetectionResult
from app.models.event import Event
from app.models.evidence import Evidence
from app.services import assessment_service, audit_service

LOW_RELIABILITY = 0.5


def _stats(values: list[float]) -> dict:
    if not values:
        return {"available": False, "reason": "no values recorded for the cited records"}
    return {"available": True, "count": len(values), "min": round(min(values), 4), "mean": round(sum(values) / len(values), 4)}


def compute_score(db: Session, assessment: Assessment, *, actor_user_id: Optional[str], rule_key: str = "review_priority_v1",
                  config_overrides: Optional[dict] = None, request_id: Optional[str] = None) -> AssessmentScoreSnapshot:
    org = assessment.organization_id
    config = scoring.resolve_config(rule_key, config_overrides)  # raises ScoringConfigError
    links = assessment_service.list_evidence_links(db, org, assessment.id)

    considered, limitations, event_ids = [], [], set()
    supporting = sum(1 for l in links if l.role == "supporting")
    contradicting = sum(1 for l in links if l.role == "contradicting")
    reliabilities, det_conf = [], []
    ev_total = ev_with_hash = 0
    synthetic_events = unreviewed_detections = 0

    for link in links:
        entry = {"link_id": link.id, "role": link.role, "note": link.note}
        if link.event_id:
            ev = db.execute(select(Event).where(Event.id == link.event_id, Event.organization_id == org)).scalar_one_or_none()
            entry.update(kind="event", id=link.event_id, title=ev.title if ev else None)
            if ev is not None:
                event_ids.add(ev.id)
                if ev.data_origin == "synthetic_demo":
                    synthetic_events += 1
                src = db.get(DataSource, ev.source_id)
                if src is not None:
                    reliabilities.append(src.reliability_weight)
                    entry["source_reliability_weight"] = src.reliability_weight
        else:
            evid = db.execute(select(Evidence).where(Evidence.id == link.evidence_id, Evidence.organization_id == org)).scalar_one_or_none()
            entry.update(kind="evidence", id=link.evidence_id, title=evid.title if evid else None, evidence_type=evid.evidence_type if evid else None)
            if evid is not None:
                ev_total += 1
                if evid.integrity_hash:
                    ev_with_hash += 1
                if evid.event_id:
                    event_ids.add(evid.event_id)
                if evid.detection_result_id:
                    det = db.get(DetectionResult, evid.detection_result_id)
                    if det is not None:
                        det_conf.append(det.confidence)
                        entry["detection_confidence"] = det.confidence
                        if det.review_status != "confirmed":
                            unreviewed_detections += 1
        considered.append(entry)

    conflicts = []
    if event_ids:
        stmt = select(Conflict).where(Conflict.organization_id == org, Conflict.review_status == "unresolved",
                                      or_(Conflict.event_a_id.in_(event_ids), Conflict.event_b_id.in_(event_ids)))
        for c in db.execute(stmt).scalars():
            conflicts.append({"conflict_id": c.id, "event_a_id": c.event_a_id, "event_b_id": c.event_b_id,
                              "conflicting_fields": c.conflicting_fields})

    gaps = list(assessment.information_gaps or [])
    missing = [{"source": "analyst", "description": str(g)} for g in gaps]
    if supporting == 0:
        missing.append({"source": "system", "description": "No supporting evidence is linked to this assessment."})
    if not assessment.confidence_level:
        missing.append({"source": "system", "description": "The analyst has not stated a confidence level."})

    if not links:
        limitations.append({"code": "no_evidence_linked", "message": "No evidence or events are linked, so nothing could be assessed for quality."})
    if ev_total and ev_with_hash < ev_total:
        limitations.append({"code": "evidence_without_integrity_hash", "message": f"{ev_total - ev_with_hash} of {ev_total} linked evidence item(s) have no integrity hash."})
    if synthetic_events:
        limitations.append({"code": "synthetic_demo_events", "message": f"{synthetic_events} cited event(s) are synthetic demonstration data."})
    low_rel = [r for r in reliabilities if r < LOW_RELIABILITY]
    if low_rel:
        limitations.append({"code": "low_reliability_sources", "message": f"{len(low_rel)} cited event(s) come from sources with a human-set reliability weight below {LOW_RELIABILITY}."})
    if unreviewed_detections:
        limitations.append({"code": "unconfirmed_detections", "message": f"{unreviewed_detections} cited detection(s) have not been confirmed by an analyst."})

    result = scoring.score_assessment(rule_key, scoring.ScoringInputs(
        contradicting_evidence_count=contradicting, unresolved_conflict_count=len(conflicts),
        information_gap_count=len(gaps), supporting_evidence_count=supporting,
        analyst_confidence_level=assessment.confidence_level), config)

    distinct = {
        "model_confidence": {**_stats(det_conf), "note": "Only from cited detections; the assessment itself is analyst-authored, not a model output."},
        "evidence_quality": {"linked_evidence_items": ev_total, "with_integrity_hash": ev_with_hash,
                             "note": "Counts only; quality is not collapsed into one number."},
        "source_reliability": {**_stats(reliabilities), "note": "Human-set weights per data source; not computed by this platform."},
        "uncertainty": {"analyst_confidence_level": assessment.confidence_level, "information_gap_count": len(gaps),
                        "unresolved_conflict_count": len(conflicts), "contradicting_evidence_count": contradicting,
                        "note": "Listed indicators, deliberately not combined into a number."},
        "assessment_priority": {"score": result["score"], "band": result["band"], "scale": scoring.SCORE_SCALE},
    }
    snap = AssessmentScoreSnapshot(
        organization_id=org, assessment_id=assessment.id, assessment_version=assessment.version,
        rule_key=rule_key, rule_version=scoring.RULES[rule_key]["version"], rule_config=config,
        score=result["score"], score_scale=scoring.SCORE_SCALE, priority_band=result["band"], factors=result["factors"],
        distinct_concepts=distinct, evidence_considered=considered, data_quality_limitations=limitations,
        conflicts=conflicts, missing_information=missing, computed_at=datetime.now(timezone.utc), computed_by_user_id=actor_user_id,
    )
    db.add(snap)
    db.flush()
    audit_service.record(db, action="assessment.score", actor_user_id=actor_user_id, organization_id=org, target_type="assessment",
                         target_id=assessment.id, request_id=request_id,
                         context_metadata={"snapshot_id": snap.id, "rule_key": rule_key, "score": snap.score, "band": snap.priority_band,
                                           "assessment_version": assessment.version})
    db.commit()
    db.refresh(snap)
    return snap


def list_snapshots(db: Session, organization_id: str, assessment_id: str) -> list[AssessmentScoreSnapshot]:
    return list(db.execute(select(AssessmentScoreSnapshot).where(
        AssessmentScoreSnapshot.organization_id == organization_id, AssessmentScoreSnapshot.assessment_id == assessment_id
    ).order_by(AssessmentScoreSnapshot.computed_at.desc(), AssessmentScoreSnapshot.id)).scalars())


def get_snapshot(db: Session, organization_id: str, assessment_id: str, snapshot_id: str) -> Optional[AssessmentScoreSnapshot]:
    return db.execute(select(AssessmentScoreSnapshot).where(
        AssessmentScoreSnapshot.id == snapshot_id, AssessmentScoreSnapshot.assessment_id == assessment_id,
        AssessmentScoreSnapshot.organization_id == organization_id)).scalar_one_or_none()
