"""Bounded evidence graph. Builds a node/edge
graph via breadth-first traversal from a seed node, STRICTLY bounded by
`max_depth` and `max_nodes` -- this never loads the whole dataset, and
a traversal that would exceed the node cap simply stops and reports
`truncated: true` rather than silently returning a partial, unlabeled
slice.

Node types: `event` (a canonical Event/"observation"), `evidence` (an
Evidence item), `assessment` (an Assessment). Edge types: `correlation`
(the EventCorrelation, event<->event only), `relationship`
(this layer's EvidenceRelationship, event/evidence <-> event/
evidence), `conflict` (a detected Conflict, event<->event),
`assessment_link` (an AssessmentEvidenceLink, assessment<->event/
evidence).

Every edge in the response carries WHY it exists (`reasons`/
`relationship_type`/`conflicting_fields` as applicable) and its
`review_status`/`origin` where applicable, so the frontend can visually
distinguish an analyst-confirmed link from an unreviewed candidate --
see docs/analytics/EVIDENCE_GRAPH.md.
"""
from __future__ import annotations

from collections import deque
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.assessment import Assessment, AssessmentEvidenceLink
from app.models.conflict import Conflict
from app.models.evidence import Evidence
from app.models.evidence_relationship import EvidenceRelationship
from app.models.event import Event
from app.models.event_correlation import EventCorrelation

settings = get_settings()


def _event_node(event: Event) -> dict:
    return {
        "id": event.id, "type": "event",
        "label": event.title,
        "data": {"event_type": event.event_type, "observed_at": event.observed_at.isoformat(), "source_id": event.source_id, "priority": event.priority},
    }


def _evidence_node(evidence: Evidence) -> dict:
    return {"id": evidence.id, "type": "evidence", "label": evidence.title, "data": {"evidence_type": evidence.evidence_type}}


def _assessment_node(assessment: Assessment) -> dict:
    return {"id": assessment.id, "type": "assessment", "label": assessment.title, "data": {"status": assessment.status, "version": assessment.version}}


def _load_node(db: Session, organization_id: str, node_type: str, node_id: str) -> Optional[dict]:
    if node_type == "event":
        row = db.execute(select(Event).where(Event.id == node_id, Event.organization_id == organization_id)).scalar_one_or_none()
        return _event_node(row) if row else None
    if node_type == "evidence":
        row = db.execute(select(Evidence).where(Evidence.id == node_id, Evidence.organization_id == organization_id)).scalar_one_or_none()
        return _evidence_node(row) if row else None
    if node_type == "assessment":
        row = db.execute(select(Assessment).where(Assessment.id == node_id, Assessment.organization_id == organization_id)).scalar_one_or_none()
        return _assessment_node(row) if row else None
    return None


def _neighbors(
    db: Session, organization_id: str, node_type: str, node_id: str, *,
    relationship_types: Optional[list[str]], review_status: Optional[str], source_id: Optional[str], since, until,
) -> list[dict]:
    """Returns edge dicts incident on (node_type, node_id), each
    carrying the OTHER endpoint as (other_type, other_id) plus the
    edge's own explanation fields. Filters are applied here, before an
    edge or its endpoint is ever added to the traversal frontier."""
    edges: list[dict] = []

    def _event_passes_filters(event_id: str) -> bool:
        if not (source_id or since or until):
            return True
        stmt = select(Event).where(Event.id == event_id, Event.organization_id == organization_id)
        event = db.execute(stmt).scalar_one_or_none()
        if event is None:
            return False
        if source_id and event.source_id != source_id:
            return False
        if since and event.observed_at < since:
            return False
        if until and event.observed_at > until:
            return False
        return True

    if node_type == "event":
        corr_stmt = select(EventCorrelation).where(
            EventCorrelation.organization_id == organization_id,
            (EventCorrelation.event_a_id == node_id) | (EventCorrelation.event_b_id == node_id),
        )
        if review_status:
            corr_stmt = corr_stmt.where(EventCorrelation.review_status == review_status)
        for corr in db.execute(corr_stmt).scalars().all():
            other_id = corr.event_b_id if corr.event_a_id == node_id else corr.event_a_id
            if not _event_passes_filters(other_id):
                continue
            edges.append({
                "id": corr.id, "type": "correlation", "origin": "rule_based",
                "source": {"type": "event", "id": corr.event_a_id}, "target": {"type": "event", "id": corr.event_b_id},
                "reasons": corr.reasons, "match_strength": corr.match_strength, "review_status": corr.review_status,
                "other": {"type": "event", "id": other_id},
            })

        conflict_stmt = select(Conflict).where(
            Conflict.organization_id == organization_id,
            (Conflict.event_a_id == node_id) | (Conflict.event_b_id == node_id),
        )
        if review_status:
            conflict_stmt = conflict_stmt.where(Conflict.review_status == review_status)
        for conflict in db.execute(conflict_stmt).scalars().all():
            other_id = conflict.event_b_id if conflict.event_a_id == node_id else conflict.event_a_id
            if not _event_passes_filters(other_id):
                continue
            edges.append({
                "id": conflict.id, "type": "conflict", "origin": "rule_based",
                "source": {"type": "event", "id": conflict.event_a_id}, "target": {"type": "event", "id": conflict.event_b_id},
                "conflicting_fields": conflict.conflicting_fields, "review_status": conflict.review_status,
                "other": {"type": "event", "id": other_id},
            })

        link_stmt = select(AssessmentEvidenceLink).where(AssessmentEvidenceLink.organization_id == organization_id, AssessmentEvidenceLink.event_id == node_id)
        for link in db.execute(link_stmt).scalars().all():
            edges.append({
                "id": link.id, "type": "assessment_link", "origin": "analyst_created",
                "source": {"type": "assessment", "id": link.assessment_id}, "target": {"type": "event", "id": node_id},
                "role": link.role, "review_status": None,
                "other": {"type": "assessment", "id": link.assessment_id},
            })

    if node_type in ("event", "evidence"):
        col = EvidenceRelationship.source_event_id if node_type == "event" else EvidenceRelationship.source_evidence_id
        col_t = EvidenceRelationship.target_event_id if node_type == "event" else EvidenceRelationship.target_evidence_id
        rel_stmt = select(EvidenceRelationship).where(
            EvidenceRelationship.organization_id == organization_id,
            (col == node_id) | (col_t == node_id),
        )
        if review_status:
            rel_stmt = rel_stmt.where(EvidenceRelationship.review_status == review_status)
        if relationship_types:
            rel_stmt = rel_stmt.where(EvidenceRelationship.relationship_type.in_(relationship_types))
        for rel in db.execute(rel_stmt).scalars().all():
            src = {"type": "event", "id": rel.source_event_id} if rel.source_event_id else {"type": "evidence", "id": rel.source_evidence_id}
            tgt = {"type": "event", "id": rel.target_event_id} if rel.target_event_id else {"type": "evidence", "id": rel.target_evidence_id}
            other = tgt if (src["type"] == node_type and src["id"] == node_id) else src
            if other["type"] == "event" and not _event_passes_filters(other["id"]):
                continue
            edges.append({
                "id": rel.id, "type": "relationship", "origin": rel.origin,
                "source": src, "target": tgt,
                "relationship_type": rel.relationship_type, "explanation": rel.explanation, "review_status": rel.review_status,
                "other": other,
            })

    if node_type == "evidence":
        link_stmt = select(AssessmentEvidenceLink).where(AssessmentEvidenceLink.organization_id == organization_id, AssessmentEvidenceLink.evidence_id == node_id)
        for link in db.execute(link_stmt).scalars().all():
            edges.append({
                "id": link.id, "type": "assessment_link", "origin": "analyst_created",
                "source": {"type": "assessment", "id": link.assessment_id}, "target": {"type": "evidence", "id": node_id},
                "role": link.role, "review_status": None,
                "other": {"type": "assessment", "id": link.assessment_id},
            })

    if node_type == "assessment":
        link_stmt = select(AssessmentEvidenceLink).where(AssessmentEvidenceLink.organization_id == organization_id, AssessmentEvidenceLink.assessment_id == node_id)
        for link in db.execute(link_stmt).scalars().all():
            other = {"type": "event", "id": link.event_id} if link.event_id else {"type": "evidence", "id": link.evidence_id}
            edges.append({
                "id": link.id, "type": "assessment_link", "origin": "analyst_created",
                "source": {"type": "assessment", "id": node_id}, "target": other,
                "role": link.role, "review_status": None,
                "other": other,
            })

    return edges


def build_graph(
    db: Session,
    organization_id: str,
    *,
    seed_type: str,
    seed_id: str,
    max_depth: Optional[int] = None,
    max_nodes: Optional[int] = None,
    relationship_types: Optional[list[str]] = None,
    review_status: Optional[str] = None,
    source_id: Optional[str] = None,
    since=None,
    until=None,
) -> dict:
    depth_cap = min(max_depth, settings.FUSION_GRAPH_MAX_DEPTH) if max_depth is not None else settings.FUSION_GRAPH_MAX_DEPTH
    node_cap = min(max_nodes, settings.FUSION_GRAPH_MAX_NODES) if max_nodes is not None else settings.FUSION_GRAPH_MAX_NODES

    seed_node = _load_node(db, organization_id, seed_type, seed_id)
    if seed_node is None:
        raise ValueError(f"no {seed_type} '{seed_id}' exists in this organization")

    nodes: dict[str, dict] = {f"{seed_type}:{seed_id}": seed_node}
    edges: dict[str, dict] = {}
    truncated = False

    queue: deque = deque([(seed_type, seed_id, 0)])
    visited = {(seed_type, seed_id)}

    while queue:
        node_type, node_id, depth = queue.popleft()
        if depth >= depth_cap:
            continue
        neighbor_edges = _neighbors(
            db, organization_id, node_type, node_id,
            relationship_types=relationship_types, review_status=review_status, source_id=source_id, since=since, until=until,
        )
        for edge in neighbor_edges:
            other_type, other_id = edge["other"]["type"], edge["other"]["id"]
            other_key = f"{other_type}:{other_id}"

            if other_key not in nodes:
                if len(nodes) >= node_cap:
                    truncated = True
                    continue
                other_node = _load_node(db, organization_id, other_type, other_id)
                if other_node is None:
                    continue
                nodes[other_key] = other_node

            edge_key = f"{edge['type']}:{edge['id']}"
            if edge_key not in edges:
                edges[edge_key] = {k: v for k, v in edge.items() if k != "other"}

            if (other_type, other_id) not in visited and other_key in nodes:
                visited.add((other_type, other_id))
                queue.append((other_type, other_id, depth + 1))

    return {
        "seed": {"type": seed_type, "id": seed_id},
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "truncated": truncated,
        "max_depth": depth_cap,
        "max_nodes": node_cap,
    }
