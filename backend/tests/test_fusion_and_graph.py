"""Fusion job orchestration and the bounded
evidence graph. Section 17 requires for the graph: empty
graph, bounded traversal, filters, authorization, and maximum
depth/result limits.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.data_source import DataSource
from app.models.event import Event
from app.services import assessment_service, correlation_service, evidence_service, fusion_service, graph_service, relationship_service

pytestmark = pytest.mark.usefixtures("referenced_rows")  # real rows for the ids these tests reference (PostgreSQL enforces FKs)


def _event(db, org, source, **overrides) -> Event:
    defaults = dict(
        organization_id=org.id, source_id=source.id, event_type="perimeter_motion", title="E",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        data_origin="user_upload",
    )
    defaults.update(overrides)
    event = Event(**defaults)
    db.add(event)
    db.flush()
    return event


# --- fusion_service ----------------------------------------------------


def test_fusion_job_runs_correlation_and_conflict_detection_together(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    _event(db, org, source, title="A", asset_id="asset-1", event_type="intrusion")
    _event(db, org, source, title="B", asset_id="asset-1", event_type="sensor_offline", observed_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc))
    db.commit()

    job = fusion_service.run_fusion_job(db, org.id, triggered_by_user_id="user-1")
    assert job.status == "completed"
    assert job.events_considered == 2
    assert job.correlations_created == 1
    assert job.conflicts_created == 1
    assert job.finished_at is not None
    assert job.rule_version == fusion_service.FUSION_RULE_VERSION


def test_fusion_job_with_no_events_completes_with_zero_counts(db, org):
    job = fusion_service.run_fusion_job(db, org.id, triggered_by_user_id="user-1")
    assert job.status == "completed"
    assert job.events_considered == 0
    assert job.correlations_created == 0
    assert job.conflicts_created == 0


def test_fusion_job_records_its_parameters(db, org):
    job = fusion_service.run_fusion_job(db, org.id, triggered_by_user_id="user-1", time_window_seconds=120, spatial_threshold_meters=50.0)
    assert job.parameters["time_window_seconds"] == 120
    assert job.parameters["spatial_threshold_meters"] == 50.0


def test_per_event_type_time_window_override_is_actually_consumed(db, org):
    """`settings.FUSION_TIME_WINDOW_SECONDS_BY_TYPE` (config.py) is not
    just a parsed-but-unused setting -- `correlation_service.recompute()`
    accepts `time_window_seconds_by_type` and widens the window for a
    pair where either side's event_type is listed. Two events with
    DIFFERENT sources/assets (so the only possible reasons are
    `compatible_event_type` and `temporal_proximity`) 3000s apart: the
    default 1800s window gives only 1 reason (below
    MIN_REASONS_FOR_CANDIDATE=2), so no correlation; a
    "sensor_offline": 3600 override supplies the second reason."""
    source_a = DataSource(organization_id=org.id, name="SA", source_type="manual")
    source_b = DataSource(organization_id=org.id, name="SB", source_type="manual")
    db.add_all([source_a, source_b])
    db.flush()
    a = _event(db, org, source_a, title="A", event_type="sensor_offline", asset_id=None)
    b = _event(
        db, org, source_b, title="B", event_type="sensor_offline", asset_id=None,
        observed_at=datetime(2026, 1, 1, 0, 50, tzinfo=timezone.utc),  # 3000s after A
    )
    db.commit()

    without_override = correlation_service.recompute(db, org.id, time_window_seconds=1800)
    assert without_override["correlations_created"] == 0

    with_override = correlation_service.recompute(
        db, org.id, time_window_seconds=1800, time_window_seconds_by_type={"sensor_offline": 3600},
    )
    assert with_override["correlations_created"] == 1


# --- graph_service -------------------------------------------------------


def test_graph_for_an_isolated_event_is_just_the_seed(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    event = _event(db, org, source, title="Lonely")
    db.commit()

    graph = graph_service.build_graph(db, org.id, seed_type="event", seed_id=event.id)
    assert len(graph["nodes"]) == 1
    assert graph["nodes"][0]["id"] == event.id
    assert graph["edges"] == []
    assert graph["truncated"] is False


def test_graph_seed_must_exist(db, org):
    with pytest.raises(ValueError):
        graph_service.build_graph(db, org.id, seed_type="event", seed_id="does-not-exist")


def test_graph_traverses_a_correlation_edge(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    a = _event(db, org, source, title="A", latitude=38.9, longitude=-77.0)
    b = _event(db, org, source, title="B", latitude=38.9001, longitude=-77.0001, observed_at=datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc))
    db.commit()
    from app.services import correlation_service
    correlation_service.recompute(db, org.id)

    graph = graph_service.build_graph(db, org.id, seed_type="event", seed_id=a.id)
    assert {n["id"] for n in graph["nodes"]} == {a.id, b.id}
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["type"] == "correlation"


def test_graph_traverses_an_analyst_relationship_to_evidence(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    event = _event(db, org, source, title="A")
    db.commit()
    note = evidence_service.create_evidence(db, organization_id=org.id, evidence_type="analyst_note", title="Note", content="text")
    relationship_service.create_relationship(
        db, organization_id=org.id, source_ref_type="event", source_ref_id=event.id, target_ref_type="evidence", target_ref_id=note.id,
        relationship_type="analyst_linked", origin="analyst_created", explanation="x", created_by_user_id="user-1",
    )

    graph = graph_service.build_graph(db, org.id, seed_type="event", seed_id=event.id)
    assert {n["id"] for n in graph["nodes"]} == {event.id, note.id}
    assert graph["edges"][0]["type"] == "relationship"
    assert graph["edges"][0]["relationship_type"] == "analyst_linked"


def test_graph_depth_limit_stops_traversal(db, org):
    """A -> B -> C chain of analyst_linked relationships via evidence
    nodes; a max_depth of 1 from A must see B but never C."""
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    a = _event(db, org, source, title="A")
    b = _event(db, org, source, title="B")
    c = _event(db, org, source, title="C")
    db.commit()
    relationship_service.create_relationship(
        db, organization_id=org.id, source_ref_type="event", source_ref_id=a.id, target_ref_type="event", target_ref_id=b.id,
        relationship_type="analyst_linked", origin="analyst_created", explanation="x", created_by_user_id="u1",
    )
    relationship_service.create_relationship(
        db, organization_id=org.id, source_ref_type="event", source_ref_id=b.id, target_ref_type="event", target_ref_id=c.id,
        relationship_type="analyst_linked", origin="analyst_created", explanation="x", created_by_user_id="u1",
    )

    shallow = graph_service.build_graph(db, org.id, seed_type="event", seed_id=a.id, max_depth=1)
    assert {n["id"] for n in shallow["nodes"]} == {a.id, b.id}

    deep = graph_service.build_graph(db, org.id, seed_type="event", seed_id=a.id, max_depth=2)
    assert {n["id"] for n in deep["nodes"]} == {a.id, b.id, c.id}


def test_graph_node_cap_truncates_and_reports_it(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    seed = _event(db, org, source, title="Seed")
    others = [_event(db, org, source, title=f"N{i}") for i in range(5)]
    db.commit()
    for other in others:
        relationship_service.create_relationship(
            db, organization_id=org.id, source_ref_type="event", source_ref_id=seed.id, target_ref_type="event", target_ref_id=other.id,
            relationship_type="analyst_linked", origin="analyst_created", explanation="x", created_by_user_id="u1",
        )

    graph = graph_service.build_graph(db, org.id, seed_type="event", seed_id=seed.id, max_nodes=3)
    assert len(graph["nodes"]) <= 3
    assert graph["truncated"] is True


def test_graph_review_status_filter(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    a = _event(db, org, source, title="A")
    b = _event(db, org, source, title="B")
    db.commit()
    relationship, _ = relationship_service.create_relationship(
        db, organization_id=org.id, source_ref_type="event", source_ref_id=a.id, target_ref_type="event", target_ref_id=b.id,
        relationship_type="analyst_linked", origin="analyst_created", explanation="x", created_by_user_id="u1",
    )

    not_confirmed_yet = graph_service.build_graph(db, org.id, seed_type="event", seed_id=a.id, review_status="confirmed")
    assert len(not_confirmed_yet["edges"]) == 0  # still "candidate"

    relationship_service.review_relationship(db, relationship, review_status="confirmed", reviewed_by_user_id="u2")
    now_confirmed = graph_service.build_graph(db, org.id, seed_type="event", seed_id=a.id, review_status="confirmed")
    assert len(now_confirmed["edges"]) == 1


def test_graph_assessment_seed_reaches_its_linked_evidence(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    event = _event(db, org, source, title="A")
    db.commit()
    assessment = assessment_service.create_assessment(db, organization_id=org.id, title="T", question="Q?", author_user_id="u1")
    assessment_service.link_evidence(db, organization_id=org.id, assessment=assessment, role="supporting", event_id=event.id, actor_user_id="u1")

    graph = graph_service.build_graph(db, org.id, seed_type="assessment", seed_id=assessment.id)
    assert {n["id"] for n in graph["nodes"]} == {assessment.id, event.id}
    assert graph["edges"][0]["type"] == "assessment_link"
    assert graph["edges"][0]["role"] == "supporting"


# --- API-level: permissions and limits -------------------------------------


def test_viewer_cannot_run_fusion_but_can_read_jobs(client, seeded_users, tokens, auth_header):
    forbidden = client.post("/api/v1/fusion/run", json={}, headers=auth_header(tokens, "viewer"))
    assert forbidden.status_code == 403

    run = client.post("/api/v1/fusion/run", json={}, headers=auth_header(tokens, "analyst"))
    assert run.status_code == 201
    assert run.json()["status"] == "completed"

    listing = client.get("/api/v1/fusion/jobs", headers=auth_header(tokens, "viewer"))
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


def test_graph_max_depth_is_clamped_server_side(client, seeded_users, tokens, source, auth_header):
    """A client asking for an absurdly large depth/node budget gets a
    200 with its request silently clamped down to the
    settings-configured hard caps (FUSION_GRAPH_MAX_DEPTH/
    FUSION_GRAPH_MAX_NODES) -- never a 422, and never the raw
    client-supplied number reflected back."""
    content = b'[{"event_type": "a", "title": "A", "observed_at": "2026-01-01T00:00:00Z"}]'
    upload = client.post("/api/v1/ingestion/jobs", data={"source_id": source.id}, files={"file": ("f.json", content, "application/json")}, headers=auth_header(tokens, "analyst"))
    event_id = client.get("/api/v1/events", headers=auth_header(tokens, "analyst")).json()["items"][0]["id"]

    response = client.get(f"/api/v1/fusion/graph?seed_type=event&seed_id={event_id}&max_depth=999&max_nodes=999999", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 200
    body = response.json()
    from app.core.config import get_settings
    settings = get_settings()
    assert body["max_depth"] == settings.FUSION_GRAPH_MAX_DEPTH
    assert body["max_nodes"] == settings.FUSION_GRAPH_MAX_NODES


def test_graph_for_nonexistent_seed_is_404(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/fusion/graph?seed_type=event&seed_id=does-not-exist", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 404
