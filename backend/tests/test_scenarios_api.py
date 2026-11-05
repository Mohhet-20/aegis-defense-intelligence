"""Scenario API -- creation/validation, versioning, runs,
idempotency/retry/failure, comparison, sensitivity, synthetic datasets,
separation from operational data, authorization, organization isolation,
exports, audit, and the retrieval/copilot integration."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.assessment import Assessment
from app.models.audit import AuditRecord
from app.models.event import Event
from app.models.observation import Observation
from app.models.organization import Organization
from app.models.retrieval import RetrievalDocument
from app.models.scenario import Scenario, ScenarioRun, SyntheticDataset
from app.models.user import User
from app.services import scenario_service as svc
from app.simulation import simulators as S
from app.simulation.errors import SimulationError

API = "/api/v1"
SETTINGS = get_settings()


@pytest.fixture()
def hdr(tokens, auth_header):
    return lambda role: auth_header(tokens, role)


@pytest.fixture()
def outsider(client, db, test_password):
    o = Organization(name="Other Org", status="active")
    db.add(o)
    db.commit()
    db.add(User(organization_id=o.id, username="outsider", email="o@x.example.com", display_name="O",
                password_hash=hash_password(test_password), role="administrator", is_active=True))
    db.commit()
    r = client.post(f"{API}/auth/login", json={"username_or_email": "outsider", "password": test_password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


BODY = {"title": "Threshold study", "template_id": "threshold_sensitivity", "assumptions": ["Gaussian noise"]}
SMALL = {"n_points": 120, "outlier_rate": 0.05}


def mk(client, h, ready=True, **over):
    body = {**BODY, "params": SMALL, **over}
    r = client.post(f"{API}/scenarios", json=body, headers=h)
    assert r.status_code == 201, r.text
    sc = r.json()
    if ready:
        assert client.post(f"{API}/scenarios/{sc['id']}/ready", headers=h).status_code == 200
        sc = client.get(f"{API}/scenarios/{sc['id']}", headers=h).json()
    return sc


def run(client, h, sid, **body):
    return client.post(f"{API}/scenarios/{sid}/runs", json=body, headers=h)


# ------------------------------------------------------------ discovery & permissions

def test_simulator_and_template_discovery_is_real_and_honest_about_gaps(client, hdr):
    r = client.get(f"{API}/simulation/simulators", headers=hdr("viewer")).json()
    assert {s["id"] for s in r["simulators"]} == set(S.REGISTRY) and r["synthetic"] is True
    assert all(p["description"] and "type" in p for s in r["simulators"] for p in s["parameters"])
    assert "run cancellation" in r["not_implemented"] and r["limits"]["max_total_runs"] == 200
    t = client.get(f"{API}/simulation/templates", headers=hdr("viewer")).json()["templates"]
    assert {x["id"] for x in t} >= {"threshold_sensitivity", "source_outages"}


def test_authentication_and_role_permissions(client, hdr):
    assert client.get(f"{API}/scenarios").status_code == 401
    assert client.post(f"{API}/scenarios", json=BODY).status_code == 401
    sc = mk(client, hdr("analyst"))
    for role in ("viewer", "investigator"):
        assert client.get(f"{API}/scenarios", headers=hdr(role)).status_code == 200
        assert client.get(f"{API}/scenarios/{sc['id']}", headers=hdr(role)).status_code == 200
        assert client.post(f"{API}/scenarios", json=BODY, headers=hdr(role)).status_code == 403
        assert run(client, hdr(role), sc["id"]).status_code == 403
        assert client.post(f"{API}/synthetic-datasets", json={"name": "x"}, headers=hdr(role)).status_code == 403
        assert client.patch(f"{API}/scenarios/{sc['id']}", json={"title": "t"}, headers=hdr(role)).status_code == 403
    assert client.post(f"{API}/scenarios", json=BODY, headers=hdr("admin")).status_code == 201


# ----------------------------------------------------------------- creation & validation

def test_create_from_template_applies_defaults_and_records_versions(client, hdr):
    r = client.post(f"{API}/scenarios", json={"title": "T", "template_id": "source_outages"}, headers=hdr("analyst"))
    sc = r.json()
    assert r.status_code == 201 and sc["status"] == "draft" and sc["version"] == 1 and sc["simulator_id"] == "source_availability"
    assert sc["simulator_version"] == S.REGISTRY["source_availability"].version and sc["question"] and sc["assumptions"]
    assert sc["params"]["n_sources"] == 3 and sc["synthetic"] is True and "SIMULATED" in sc["label"]


@pytest.mark.parametrize("body", [
    {"title": "x"},                                                              # no simulator / template
    {"title": "x", "simulator_id": "does_not_exist"},
    {"title": "x", "simulator_id": "__import__('os').system('id')"},
    {"title": "x", "template_id": "nope"},
    {"title": "x", "template_id": "source_outages", "simulator_id": "threshold_detection"},
    {"title": "x", "simulator_id": "threshold_detection", "params": {"n_points": 10**9}},
    {"title": "x", "simulator_id": "threshold_detection", "params": {"n_points": "5; DROP TABLE scenarios"}},
    {"title": "x", "simulator_id": "threshold_detection", "params": {"shell": "rm -rf /"}},
    {"title": "x", "simulator_id": "threshold_detection", "execution_config": {"max_seconds": 10**6}},
    {"title": "x", "simulator_id": "threshold_detection", "execution_config": {"command": "ls"}},
    {"title": "", "simulator_id": "threshold_detection"},
    {"title": "x" * 201, "simulator_id": "threshold_detection"},
    {"title": "x", "simulator_id": "threshold_detection", "seed": -1},
    {"title": "x", "simulator_id": "threshold_detection", "unexpected_field": 1},
    {"title": "x", "simulator_id": "threshold_detection", "assumptions": ["a"] * 31},
])
def test_invalid_scenarios_are_rejected_with_422(client, hdr, db, body):
    r = client.post(f"{API}/scenarios", json=body, headers=hdr("analyst"))
    assert r.status_code == 422, r.text
    assert db.scalar(select(func.count()).select_from(Scenario)) == 0


def test_validate_endpoint_reports_each_error_without_persisting(client, hdr, db):
    r = client.post(f"{API}/scenarios/validate", json={"simulator_id": "threshold_detection", "params": {"noise_sd": -1, "zzz": 1}}, headers=hdr("analyst")).json()
    assert r["valid"] is False and {e["param"] for e in r["errors"]} == {"noise_sd", "zzz"}
    ok = client.post(f"{API}/scenarios/validate", json={"simulator_id": "threshold_detection", "params": {"noise_sd": 2}}, headers=hdr("analyst")).json()
    assert ok["valid"] and ok["params"]["noise_sd"] == 2 and ok["assumptions"] and ok["limitations"]
    assert client.post(f"{API}/scenarios/validate", json={"simulator_id": "nope"}, headers=hdr("analyst")).json()["valid"] is False
    assert db.scalar(select(func.count()).select_from(Scenario)) == 0


def test_scenario_count_limit(client, hdr, monkeypatch):
    monkeypatch.setattr(svc.settings, "SCENARIO_MAX_SCENARIOS_PER_ORG", 1)
    mk(client, hdr("analyst"), ready=False)
    assert client.post(f"{API}/scenarios", json={**BODY, "params": SMALL}, headers=hdr("analyst")).status_code == 409


# ------------------------------------------------------- draft / ready / versions

def test_draft_can_be_edited_ready_requires_assumptions_and_is_then_immutable(client, hdr):
    A = hdr("analyst")
    sc = client.post(f"{API}/scenarios", json={"title": "No template", "simulator_id": "threshold_detection", "params": SMALL}, headers=A).json()
    assert sc["assumptions"] == []
    assert client.post(f"{API}/scenarios/{sc['id']}/ready", headers=A).status_code == 422  # no assumptions recorded
    r = client.patch(f"{API}/scenarios/{sc['id']}", json={"params": {"noise_sd": 2.5}, "assumptions": ["IID noise"], "title": "Edited"}, headers=A)
    assert r.status_code == 200 and r.json()["params"]["noise_sd"] == 2.5 and r.json()["params"]["n_points"] == 120 and r.json()["title"] == "Edited"
    assert client.patch(f"{API}/scenarios/{sc['id']}", json={"params": {"noise_sd": -3}}, headers=A).status_code == 422
    assert client.post(f"{API}/scenarios/{sc['id']}/ready", headers=A).json()["status"] == "ready"
    assert client.patch(f"{API}/scenarios/{sc['id']}", json={"title": "Nope"}, headers=A).status_code == 409
    assert client.post(f"{API}/scenarios/{sc['id']}/ready", headers=A).status_code == 409


def test_duplicate_creates_next_version_in_same_lineage_and_keeps_history(client, hdr):
    A = hdr("analyst")
    v1 = mk(client, A)
    d = client.post(f"{API}/scenarios/{v1['id']}/duplicate", json={"params": {"noise_sd": 3.0}}, headers=A)
    v2 = d.json()
    assert d.status_code == 201 and v2["version"] == 2 and v2["lineage_id"] == v1["lineage_id"] and v2["parent_scenario_id"] == v1["id"]
    assert v2["status"] == "draft" and v2["params"]["noise_sd"] == 3.0 and v2["assumptions"] == v1["assumptions"]
    v3 = client.post(f"{API}/scenarios/{v1['id']}/duplicate", json={}, headers=A).json()
    assert v3["version"] == 3
    vs = client.get(f"{API}/scenarios/{v2['id']}/versions", headers=A).json()
    assert [v["version"] for v in vs] == [1, 2, 3]
    assert client.get(f"{API}/scenarios/{v1['id']}", headers=A).json()["params"]["noise_sd"] == v1["params"]["noise_sd"]  # v1 untouched
    latest = client.get(f"{API}/scenarios", params={"latest_only": True}, headers=A).json()
    assert [s["version"] for s in latest["items"]] == [3]
    assert client.post(f"{API}/scenarios/{v1['id']}/duplicate", json={"params": {"noise_sd": -1}}, headers=A).status_code == 422


def test_list_filters_and_pagination(client, hdr):
    A = hdr("analyst")
    a = mk(client, A, title="Alpha study")
    mk(client, A, ready=False, title="Beta", template_id="source_outages", params={})
    assert client.get(f"{API}/scenarios", params={"status": "ready"}, headers=A).json()["total"] == 1
    assert client.get(f"{API}/scenarios", params={"simulator_id": "source_availability"}, headers=A).json()["total"] == 1
    assert client.get(f"{API}/scenarios", params={"q": "alph"}, headers=A).json()["items"][0]["id"] == a["id"]
    p = client.get(f"{API}/scenarios", params={"page_size": 1, "page": 2}, headers=A).json()
    assert p["total"] == 2 and len(p["items"]) == 1
    assert client.get(f"{API}/scenarios", params={"status": "bogus"}, headers=A).status_code == 422
    assert client.get(f"{API}/scenarios", params={"page_size": 1000}, headers=A).status_code == 422


def test_archive_blocks_running(client, hdr):
    A = hdr("analyst")
    sc = mk(client, A)
    assert client.post(f"{API}/scenarios/{sc['id']}/archive", headers=A).json()["status"] == "archived"
    assert run(client, A, sc["id"]).status_code == 409


# ---------------------------------------------------------------------- runs

def test_run_requires_ready_scenario(client, hdr, db):
    sc = mk(client, hdr("analyst"), ready=False)
    assert run(client, hdr("analyst"), sc["id"]).status_code == 409
    assert db.scalar(select(func.count()).select_from(ScenarioRun)) == 0


def test_completed_run_records_snapshot_runtime_hash_and_labels(client, hdr, db):
    A = hdr("analyst")
    sc = mk(client, A)
    r = run(client, A, sc["id"])
    d = r.json()
    assert r.status_code == 201 and d["status"] == "completed" and d["synthetic"] is True and "SIMULATED" in d["label"]
    assert isinstance(d["runtime_ms"], int) and d["runtime_ms"] >= 0 and d["started_at"] and d["completed_at"] and d["error_code"] is None
    snap = d["config_snapshot"]
    assert snap["scenario_id"] == sc["id"] and snap["scenario_version"] == 1 and snap["simulator_id"] == "threshold_detection"
    assert snap["params"] == sc["params"] and snap["seed"] == d["seed"] == sc["seed"] and snap["assumptions"] == sc["assumptions"] and snap["synthetic"] is True
    assert set(d["results"]["metrics"]) == {m.name for m in S.get("threshold_detection").metrics}
    assert d["results"]["dataset_header"]["synthetic"] is True and d["dataset_ref"]["synthetic"] is True and len(d["result_sha256"]) == 64
    sc2 = client.get(f"{API}/scenarios/{sc['id']}", headers=A).json()
    assert sc2["latest_summary"]["run_id"] == d["id"] and sc2["latest_summary"]["metrics"] == d["results"]["metrics"]
    assert client.get(f"{API}/scenario-runs/{d['id']}", headers=A).json()["result_sha256"] == d["result_sha256"]


def test_same_seed_reproduces_identical_results_and_different_seed_does_not(client, hdr):
    A = hdr("analyst")
    sc = mk(client, A)
    r1, r2, r3 = run(client, A, sc["id"]).json(), run(client, A, sc["id"]).json(), run(client, A, sc["id"], seed=99).json()
    assert r1["result_sha256"] == r2["result_sha256"] and r1["id"] != r2["id"]
    assert r3["seed"] == 99 and r3["config_snapshot"]["seed"] == 99 and r3["result_sha256"] != r1["result_sha256"]


def test_runs_do_not_overwrite_history_and_are_listed_newest_first(client, hdr):
    A = hdr("analyst")
    sc = mk(client, A)
    ids = [run(client, A, sc["id"], seed=i).json()["id"] for i in (1, 2, 3)]
    page = client.get(f"{API}/scenarios/{sc['id']}/runs", headers=A).json()
    assert page["total"] == 3 and set(i["id"] for i in page["items"]) == set(ids)
    assert "results" not in page["items"][0] and "config_snapshot" not in page["items"][0]  # summaries only
    assert client.get(f"{API}/scenarios/{sc['id']}/runs", params={"status": "failed"}, headers=A).json()["total"] == 0
    assert client.get(f"{API}/scenarios/{sc['id']}/runs", params={"kind": "bad"}, headers=A).status_code == 422


def test_idempotency_key_replays_without_running_again(client, hdr, db):
    A = hdr("analyst")
    sc = mk(client, A)
    h = {**A, "Idempotency-Key": "abc-123"}
    first = client.post(f"{API}/scenarios/{sc['id']}/runs", json={}, headers=h)
    again = client.post(f"{API}/scenarios/{sc['id']}/runs", json={}, headers=h)
    assert first.status_code == 201 and again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert again.json()["idempotent_replay"] is True and db.scalar(select(func.count()).select_from(ScenarioRun)) == 1
    other = client.post(f"{API}/scenarios/{sc['id']}/runs", json={}, headers={**A, "Idempotency-Key": "xyz"})
    assert other.status_code == 201 and other.json()["id"] != first.json()["id"]
    assert client.post(f"{API}/scenarios/{sc['id']}/runs", json={}, headers={**A, "Idempotency-Key": "k" * 101}).status_code == 422


def test_second_run_is_refused_while_one_is_in_progress_and_stale_runs_are_expired(client, hdr, db):
    A = hdr("analyst")
    sc = mk(client, A)
    now = datetime.now(timezone.utc)
    row = ScenarioRun(organization_id=sc["id"] and db.get(Scenario, sc["id"]).organization_id, scenario_id=sc["id"], scenario_version=1, run_kind="simulation",
                      status="running", config_snapshot={}, simulator_id="threshold_detection", simulator_version="1.0.0", seed=1,
                      started_at=now, requested_by_user_id="u")
    db.add(row)
    db.commit()
    assert run(client, A, sc["id"]).status_code == 409
    row.started_at = now - timedelta(seconds=SETTINGS.SCENARIO_STALE_RUN_SECONDS + 10)
    db.commit()
    ok = run(client, A, sc["id"])
    assert ok.status_code == 201, ok.text
    assert ok.json()["status"] == "completed"
    db.expire_all()
    stale = db.get(ScenarioRun, row.id)
    assert stale.status == "failed" and stale.error_code == "stale_run" and stale.results is None  # never reported as completed


def test_failed_run_is_recorded_safely_and_can_be_retried(client, hdr, db, monkeypatch):
    A = hdr("analyst")
    sc = mk(client, A)
    real = S.execute
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SimulationError("numerical error during simulation (ValueError)", "numerical_error")
        return real(*a, **k)
    monkeypatch.setattr(S, "execute", flaky)
    bad = run(client, A, sc["id"]).json()
    assert bad["status"] == "failed" and bad["error_code"] == "numerical_error" and bad["results"] is None and bad["result_sha256"] is None
    assert bad["completed_at"] and isinstance(bad["runtime_ms"], int)
    assert client.get(f"{API}/scenarios/{sc['id']}", headers=A).json()["latest_summary"] is None  # failure never becomes a summary
    retry = client.post(f"{API}/scenario-runs/{bad['id']}/retry", headers=A)
    good = retry.json()
    assert retry.status_code == 201 and good["status"] == "completed" and good["retry_of_run_id"] == bad["id"] and good["id"] != bad["id"]
    assert client.get(f"{API}/scenario-runs/{bad['id']}", headers=A).json()["status"] == "failed"  # history intact
    assert client.post(f"{API}/scenario-runs/{good['id']}/retry", headers=A).status_code == 409  # only failed runs retry


def test_unexpected_exception_does_not_leak_internals(client, hdr, monkeypatch):
    A = hdr("analyst")
    sc = mk(client, A)

    def boom(*a, **k):
        raise RuntimeError("secret /etc/passwd path and SQL select * from users")
    monkeypatch.setattr(S, "execute", boom)
    d = run(client, A, sc["id"]).json()
    assert d["status"] == "failed" and d["error_code"] == "internal_error"
    assert "secret" not in json.dumps(d) and "passwd" not in json.dumps(d)


def test_oversized_result_is_discarded_not_stored_as_completed(client, hdr, monkeypatch):
    A = hdr("analyst")
    sc = mk(client, A)
    monkeypatch.setattr(svc.settings, "SCENARIO_MAX_RESULT_BYTES", 100)
    d = run(client, A, sc["id"]).json()
    assert d["status"] == "failed" and d["error_code"] == "resource_limit" and d["results"] is None


def test_time_budget_from_execution_config_is_enforced(client, hdr):
    A = hdr("analyst")
    sc = mk(client, A, execution_config={"max_seconds": 0.1}, params={"n_points": 5000})
    d = run(client, A, sc["id"]).json()
    assert d["status"] in ("completed", "failed")
    if d["status"] == "failed":
        assert d["error_code"] in ("resource_limit", "timeout", "simulation_error") and d["results"] is None


def test_run_history_cap(client, hdr, monkeypatch):
    A = hdr("analyst")
    monkeypatch.setattr(svc.settings, "SCENARIO_MAX_RUNS_PER_SCENARIO", 2)
    sc = mk(client, A)
    assert run(client, A, sc["id"]).status_code == 201 and run(client, A, sc["id"], seed=2).status_code == 201
    assert run(client, A, sc["id"], seed=3).status_code == 409


def test_unknown_request_fields_and_bad_seed_rejected(client, hdr):
    A = hdr("analyst")
    sc = mk(client, A)
    assert run(client, A, sc["id"], seed=-5).status_code == 422
    assert run(client, A, sc["id"], simulator_id="os.system").status_code == 422
    assert run(client, A, sc["id"], params={"n_points": 1}).status_code == 422  # params cannot be overridden at run time


# ---------------------------------------------------------------- comparison

def two_runs(client, A, **alt_params):
    v1 = mk(client, A)
    v2 = client.post(f"{API}/scenarios/{v1['id']}/duplicate", json={"params": alt_params}, headers=A).json()
    client.post(f"{API}/scenarios/{v2['id']}/ready", headers=A)
    return run(client, A, v1["id"]).json(), run(client, A, v2["id"]).json()


def test_compare_single_parameter_change(client, hdr):
    A = hdr("analyst")
    base, alt = two_runs(client, A, noise_sd=3.0)
    r = client.post(f"{API}/scenario-comparisons", json={"baseline_run_id": base["id"], "alternative_run_ids": [alt["id"]]}, headers=hdr("viewer"))
    c = r.json()
    assert r.status_code == 200 and c["synthetic"] is True and "SIMULATED" in c["label"]
    a = c["alternatives"][0]
    assert a["attribution"]["status"] == "single_parameter" and [x["param"] for x in a["parameter_changes"]] == ["noise_sd"]
    assert a["parameter_changes"][0] == {"param": "noise_sd", "baseline": 1.0, "alternative": 3.0} and a["seed_changed"] is False
    assert any("causal" in x for x in c["caveats"]) and c["assumptions"] and c["limitations"]
    m = {x["name"]: x for x in a["metrics"]}
    assert m["false_positives"]["absolute_diff"] == alt["results"]["metrics"]["false_positives"] - base["results"]["metrics"]["false_positives"]


def test_compare_with_several_changes_refuses_single_attribution(client, hdr):
    base, alt = two_runs(client, hdr("analyst"), noise_sd=3.0, threshold_k=7.0)
    a = client.post(f"{API}/scenario-comparisons", json={"baseline_run_id": base["id"], "alternative_run_ids": [alt["id"]]}, headers=hdr("analyst")).json()["alternatives"][0]
    assert a["attribution"]["status"] == "multiple_inputs" and len(a["parameter_changes"]) == 2


def test_compare_rejects_bad_inputs(client, hdr, monkeypatch):
    A = hdr("analyst")
    base, alt = two_runs(client, A, noise_sd=2.0)
    post = lambda b, alts: client.post(f"{API}/scenario-comparisons", json={"baseline_run_id": b, "alternative_run_ids": alts}, headers=A)  # noqa: E731
    assert post(base["id"], [base["id"]]).status_code == 422                 # not distinct
    assert post(base["id"], [alt["id"]] * 2).status_code == 422
    assert post(base["id"], []).status_code == 422
    assert post(base["id"], ["a", "b", "c", "d"]).status_code == 422
    assert post(base["id"], ["no-such-run"]).status_code == 404
    sens = client.post(f"{API}/scenarios/{alt['config_snapshot']['scenario_id']}/sensitivity",
                       json={"sweep": [{"param": "threshold_k", "values": [3, 5]}], "repetitions": 2, "metric": "f1"}, headers=A).json()
    assert post(base["id"], [sens["id"]]).status_code == 422                 # sensitivity runs are not comparable


# --------------------------------------------------------------- sensitivity

def test_sensitivity_run_is_stored_labelled_and_reproducible(client, hdr, db):
    A = hdr("analyst")
    sc = mk(client, A)
    body = {"sweep": [{"param": "threshold_k", "values": [2, 4, 8]}, {"param": "noise_sd", "min": 0.5, "max": 2.5, "steps": 3}], "repetitions": 3, "metric": "f1"}
    r = client.post(f"{API}/scenarios/{sc['id']}/sensitivity", json=body, headers=A)
    d = r.json()
    assert r.status_code == 201 and d["status"] == "completed" and d["run_kind"] == "sensitivity" and d["results"]["total_runs"] == 21
    assert d["results"]["method"] == "one_parameter_at_a_time" and d["results"]["synthetic"] is True and d["results"]["ranking"]
    assert d["config_snapshot"]["sensitivity"]["planned_runs"] == 21 and "SIMULATED" in d["results"]["label"]
    again = client.post(f"{API}/scenarios/{sc['id']}/sensitivity", json=body, headers=A).json()
    assert again["result_sha256"] == d["result_sha256"]
    assert client.get(f"{API}/scenarios/{sc['id']}/runs", params={"kind": "sensitivity"}, headers=A).json()["total"] == 2
    assert client.get(f"{API}/scenarios/{sc['id']}", headers=A).json()["latest_summary"] is None  # sweeps never set the headline summary


@pytest.mark.parametrize("body", [
    {"sweep": [], "repetitions": 3, "metric": "f1"},
    {"sweep": [{"param": "noise_sd", "values": [1, 2]}], "repetitions": 21, "metric": "f1"},
    {"sweep": [{"param": "noise_sd", "values": [1, 2]}], "repetitions": 3, "metric": "nope"},
    {"sweep": [{"param": "noise_sd", "values": [1, 2]}] * 2, "repetitions": 3, "metric": "f1"},
    {"sweep": [{"param": "noise_sd", "values": [-1, 2]}], "repetitions": 3, "metric": "f1"},
    {"sweep": [{"param": "nope", "values": [1, 2]}], "repetitions": 3, "metric": "f1"},
    {"sweep": [{"param": "noise_sd", "min": 0, "max": 1, "steps": 12}], "repetitions": 3, "metric": "f1"},
    {"sweep": [{"param": f"p{i}", "values": [1, 2]} for i in range(5)], "repetitions": 3, "metric": "f1"},
    {"sweep": [{"param": "threshold_k", "min": 2, "max": 10, "steps": 9}, {"param": "noise_sd", "min": 0.1, "max": 2, "steps": 9},
               {"param": "outlier_rate", "min": 0.01, "max": 0.1, "steps": 9}], "repetitions": 20, "metric": "f1"},
    {"sweep": [{"param": "noise_sd", "values": [1, 2]}], "repetitions": 3, "metric": "f1", "extra": 1},
])
def test_invalid_or_oversized_sweeps_are_rejected_and_create_no_run(client, hdr, db, body):
    A = hdr("analyst")
    sc = mk(client, A)
    assert client.post(f"{API}/scenarios/{sc['id']}/sensitivity", json=body, headers=A).status_code == 422
    assert db.scalar(select(func.count()).select_from(ScenarioRun)) == 0


# ------------------------------------------------------- synthetic datasets

def test_dataset_generation_is_deterministic_labelled_and_isolated(client, hdr, db):
    A = hdr("analyst")
    before = [db.scalar(select(func.count()).select_from(m)) for m in (Observation, Event, Assessment)]
    body = {"name": "Fixture A", "params": {"n_points": 80, "n_sources": 2, "missing_rate": 0.1, "duplicate_rate": 0.05}, "seed": 42}
    r = client.post(f"{API}/synthetic-datasets", json=body, headers=A)
    d = r.json()
    assert r.status_code == 201 and d["is_synthetic"] is True and d["synthetic"] is True and "SYNTHETIC" in d["label"]
    assert d["seed"] == 42 and d["record_count"] > 0 and d["generator"] and d["generator_version"] and len(d["content_sha256"]) == 64
    d2 = client.post(f"{API}/synthetic-datasets", json={**body, "name": "Fixture B"}, headers=A).json()
    assert d2["content_sha256"] == d["content_sha256"] and d2["id"] != d["id"]
    full = client.get(f"{API}/synthetic-datasets/{d['id']}", params={"limit": 5}, headers=hdr("viewer")).json()
    assert full["header"]["synthetic"] is True and full["header"]["limitations"] and full["header"]["seed"] == 42 and "generated_at" in full["header"]
    assert len(full["records"]) == 5 and all(x["synthetic"] is True for x in full["records"]) and full["records_returned"] == 5
    after = [db.scalar(select(func.count()).select_from(m)) for m in (Observation, Event, Assessment)]
    assert before == after  # nothing leaks into operational tables
    assert client.get(f"{API}/synthetic-datasets", headers=hdr("viewer")).json()["total"] == 2


@pytest.mark.parametrize("params", [{"n_points": 10**7}, {"n_points": 5000, "n_sources": 5}, {"bogus": 1}, {"missing_rate": 1.5}, {"noise_sd": "big"}])
def test_dataset_size_and_parameter_guards(client, hdr, db, params):
    r = client.post(f"{API}/synthetic-datasets", json={"name": "x", "params": params}, headers=hdr("analyst"))
    assert r.status_code == 422
    assert db.scalar(select(func.count()).select_from(SyntheticDataset)) == 0


def test_large_dataset_is_truncated_in_storage_but_counted(client, hdr, db):
    r = client.post(f"{API}/synthetic-datasets", json={"name": "big", "params": {"n_points": 3000, "n_sources": 3}}, headers=hdr("analyst")).json()
    assert r["record_count"] > r["stored_record_count"] == 5000 and r["records_truncated"] is True
    assert client.get(f"{API}/synthetic-datasets/{r['id']}", params={"limit": 501}, headers=hdr("analyst")).status_code == 422


def test_dataset_count_limit(client, hdr, monkeypatch):
    monkeypatch.setattr(svc.settings, "SCENARIO_MAX_DATASETS_PER_ORG", 1)
    assert client.post(f"{API}/synthetic-datasets", json={"name": "a", "params": {"n_points": 10}}, headers=hdr("analyst")).status_code == 201
    assert client.post(f"{API}/synthetic-datasets", json={"name": "b", "params": {"n_points": 10}}, headers=hdr("analyst")).status_code == 409


def test_simulation_runs_never_write_operational_tables(client, hdr, db):
    A = hdr("analyst")
    before = [db.scalar(select(func.count()).select_from(m)) for m in (Observation, Event, Assessment)]
    sc = mk(client, A)
    run(client, A, sc["id"])
    client.post(f"{API}/scenarios/{sc['id']}/sensitivity", json={"sweep": [{"param": "threshold_k", "values": [3, 5]}], "repetitions": 2, "metric": "f1"}, headers=A)
    assert before == [db.scalar(select(func.count()).select_from(m)) for m in (Observation, Event, Assessment)]


# --------------------------------------------------------- isolation & security

def test_other_organization_cannot_see_or_touch_anything(client, hdr, outsider):
    A = hdr("analyst")
    sc = mk(client, A)
    r = run(client, A, sc["id"]).json()
    ds = client.post(f"{API}/synthetic-datasets", json={"name": "d", "params": {"n_points": 10}}, headers=A).json()
    O = outsider
    for method, path, kw in [
        ("get", f"/scenarios/{sc['id']}", {}), ("patch", f"/scenarios/{sc['id']}", {"json": {"title": "x"}}),
        ("post", f"/scenarios/{sc['id']}/ready", {}), ("post", f"/scenarios/{sc['id']}/duplicate", {"json": {}}),
        ("post", f"/scenarios/{sc['id']}/archive", {}), ("get", f"/scenarios/{sc['id']}/versions", {}),
        ("get", f"/scenarios/{sc['id']}/runs", {}), ("post", f"/scenarios/{sc['id']}/runs", {"json": {}}),
        ("get", f"/scenarios/{sc['id']}/export", {}), ("get", f"/scenario-runs/{r['id']}", {}),
        ("post", f"/scenario-runs/{r['id']}/retry", {}), ("get", f"/synthetic-datasets/{ds['id']}", {}),
        ("post", f"/scenarios/{sc['id']}/sensitivity", {"json": {"sweep": [{"param": "noise_sd", "values": [1, 2]}], "repetitions": 2, "metric": "f1"}}),
        ("post", "/scenario-comparisons", {"json": {"baseline_run_id": r["id"], "alternative_run_ids": [r["id"]]}}),
    ]:
        resp = getattr(client, method)(f"{API}{path}", headers=O, **kw)
        assert resp.status_code in (404, 422), (path, resp.status_code)
        if resp.status_code == 404:
            assert resp.json()["detail"].endswith("not found")
    assert client.get(f"{API}/scenarios", headers=O).json()["total"] == 0
    assert client.get(f"{API}/synthetic-datasets", headers=O).json()["total"] == 0
    cmp_ = client.post(f"{API}/scenario-comparisons", json={"baseline_run_id": r["id"], "alternative_run_ids": ["x"]}, headers=O)
    assert cmp_.status_code == 404


def test_restricted_investigation_scenarios_follow_investigation_access(client, hdr, seeded_users):
    A = hdr("analyst")
    inv = client.post(f"{API}/investigations", json={"title": "Vault", "is_restricted": True, "assigned_user_id": seeded_users["analyst"].id}, headers=A).json()
    sc = mk(client, A, investigation_id=inv["id"])
    assert client.get(f"{API}/scenarios/{sc['id']}", headers=A).status_code == 200
    for role in ("viewer", "investigator"):
        assert client.get(f"{API}/scenarios/{sc['id']}", headers=hdr(role)).status_code == 404
        assert sc["id"] not in [s["id"] for s in client.get(f"{API}/scenarios", headers=hdr(role)).json()["items"]]
        assert client.get(f"{API}/scenarios/{sc['id']}/export", headers=hdr(role)).status_code == 404
    assert client.get(f"{API}/scenarios/{sc['id']}", headers=hdr("admin")).status_code == 200
    # cannot attach a scenario to an investigation you cannot access
    assert client.post(f"{API}/scenarios", json={**BODY, "investigation_id": inv["id"]}, headers=hdr("admin")).status_code == 201
    r = client.post(f"{API}/scenarios", json={**BODY, "investigation_id": "no-such"}, headers=A)
    assert r.status_code == 404


# -------------------------------------------------------------------- export

def test_exports_are_labelled_simulated_with_provenance_and_safe_headers(client, hdr):
    A = hdr("analyst")
    sc = mk(client, A)
    d = run(client, A, sc["id"]).json()
    j = client.get(f"{API}/scenarios/{sc['id']}/export", headers=hdr("viewer"))
    assert j.status_code == 200 and j.headers["content-type"].startswith("application/json") and j.headers["x-aegis-synthetic"] == "true"
    assert j.headers["content-disposition"] == f'attachment; filename="scenario-{sc["id"]}.json"' and j.headers["x-content-type-options"] == "nosniff"
    doc = j.json()
    assert doc["synthetic"] is True and "SIMULATED" in doc["label"] and doc["scenario"]["id"] == sc["id"]
    assert doc["runs"][0]["run_id"] == d["id"] and doc["runs"][0]["result_sha256"] == d["result_sha256"] and doc["runs"][0]["metrics"] == d["results"]["metrics"]
    assert any("not evidence" in x for x in doc["interpretation"])
    m = client.get(f"{API}/scenarios/{sc['id']}/export", params={"format": "markdown"}, headers=A)
    assert m.status_code == 200 and m.text.startswith("# [SIMULATED]") and "SIMULATED" in m.text.splitlines()[2] and d["result_sha256"] in m.text
    assert m.headers["content-disposition"].endswith('.md"')


@pytest.mark.parametrize("fmt", ["../../etc/passwd", "csv", "json;rm", "%2e%2e"])
def test_export_format_is_whitelisted(client, hdr, fmt):
    sc = mk(client, hdr("analyst"))
    assert client.get(f"{API}/scenarios/{sc['id']}/export", params={"format": fmt}, headers=hdr("analyst")).status_code == 422


def test_path_traversal_ids_are_just_not_found(client, hdr):
    A = hdr("analyst")
    for bad in ("..%2f..%2fetc%2fpasswd", "../x", "' OR 1=1 --"):
        assert client.get(f"{API}/scenarios/{bad}", headers=A).status_code == 404
        assert client.get(f"{API}/scenario-runs/{bad}", headers=A).status_code == 404
        assert client.get(f"{API}/synthetic-datasets/{bad}", headers=A).status_code == 404


# --------------------------------------------------------------------- audit

def test_audit_records_for_configuration_and_execution(client, hdr, db):
    A = hdr("analyst")
    sc = mk(client, A)
    r = run(client, A, sc["id"]).json()
    client.post(f"{API}/scenarios/{sc['id']}/duplicate", json={}, headers=A)
    client.post(f"{API}/scenario-comparisons", json={"baseline_run_id": r["id"], "alternative_run_ids": [run(client, A, sc["id"], seed=3).json()["id"]]}, headers=A)
    client.get(f"{API}/scenarios/{sc['id']}/export", headers=A)
    client.post(f"{API}/synthetic-datasets", json={"name": "d", "params": {"n_points": 10}}, headers=A)
    actions = {a for (a,) in db.execute(select(AuditRecord.action).where(AuditRecord.action.like("scenario.%") | AuditRecord.action.like("dataset.%")))}
    assert actions >= {"scenario.create", "scenario.ready", "scenario.run", "scenario.duplicate", "scenario.compare", "scenario.export", "dataset.generate"}
    row = db.scalars(select(AuditRecord).where(AuditRecord.action == "scenario.run", AuditRecord.target_id == r["id"])).one()
    assert row.outcome == "success" and "metrics" not in json.dumps(row.context_metadata or {})


# ------------------------------------------------------ retrieval / copilot hook

def index_scenarios(client, h):
    return client.post(f"{API}/retrieval/index", json={"record_types": ["scenario"]}, headers=h)


def test_scenarios_are_indexed_with_type_metadata_and_excluded_from_default_search(client, hdr, db):
    A = hdr("analyst")
    sc = mk(client, A, title="Zebracrossing calibration", question="How does zebracrossing noise affect detection?")
    run(client, A, sc["id"])
    assert index_scenarios(client, hdr("admin")).status_code == 200
    doc = db.scalars(select(RetrievalDocument).where(RetrievalDocument.record_type == "scenario")).one()
    assert doc.title.startswith("[SIMULATED]") and doc.record_id == sc["id"]
    default = client.get(f"{API}/retrieval/search", params={"q": "zebracrossing"}, headers=A).json()
    assert default["total"] == 0                                              # not mixed into factual results
    explicit = client.get(f"{API}/retrieval/search", params={"q": "zebracrossing", "record_type": "scenario"}, headers=A).json()
    hit = explicit["items"][0]
    assert explicit["total"] == 1 and hit["record_type"] == "scenario" and hit["title"].startswith("[SIMULATED]") and hit["link"] == f"/scenarios/{sc['id']}"
    assert client.get(f"{API}/retrieval/documents/scenario/{sc['id']}", headers=A).json()["title"].startswith("[SIMULATED]")


def test_runs_and_datasets_are_never_indexed(client, hdr, db):
    A = hdr("analyst")
    sc = mk(client, A)
    run(client, A, sc["id"])
    client.post(f"{API}/synthetic-datasets", json={"name": "d", "params": {"n_points": 10}}, headers=A)
    assert client.post(f"{API}/retrieval/index", json={}, headers=hdr("admin")).status_code == 200
    types = {t for (t,) in db.execute(select(RetrievalDocument.record_type).distinct())}
    assert types <= {"scenario", "investigation", "investigation_note", "event", "observation", "assessment", "assessment_review", "evidence", "data_source", "media_asset"}
    assert client.post(f"{API}/retrieval/index", json={"record_types": ["scenario_run"]}, headers=hdr("admin")).status_code == 422


def test_copilot_labels_simulation_output_as_hypothetical(client, hdr):
    A = hdr("analyst")
    sc = mk(client, A, title="Quokka drift scenario", question="Quokka drift effect on alarms?")
    run(client, A, sc["id"])
    index_scenarios(client, hdr("admin"))
    plain = client.post(f"{API}/copilot/ask", json={"task": "question", "question": "quokka drift"}, headers=A).json()["answer"]
    assert plain["citations"] == [] and not any("SIMULATED" in u for u in plain["uncertainty"])  # excluded unless requested
    ans = client.post(f"{API}/copilot/ask", json={"task": "question", "question": "quokka drift", "record_types": ["scenario"], "save": False}, headers=A).json()["answer"]
    assert ans["citations"] and all(c["record_type"] == "scenario" for c in ans["citations"])
    assert any("SIMULATED" in u and "not evidence" in u for u in ans["uncertainty"])
    assert any("[SIMULATED]" in (c["title"] or "") for c in ans["citations"])


def test_restricted_scenario_not_searchable_by_non_members(client, hdr, seeded_users):
    A = hdr("analyst")
    inv = client.post(f"{API}/investigations", json={"title": "Vault", "is_restricted": True, "assigned_user_id": seeded_users["analyst"].id}, headers=A).json()
    sc = mk(client, A, title="Narwhal secrecy study", investigation_id=inv["id"])
    index_scenarios(client, hdr("admin"))
    q = {"q": "narwhal", "record_type": "scenario"}
    assert client.get(f"{API}/retrieval/search", params=q, headers=A).json()["total"] == 1
    assert client.get(f"{API}/retrieval/search", params=q, headers=hdr("investigator")).json()["total"] == 0
    assert client.get(f"{API}/retrieval/documents/scenario/{sc['id']}", headers=hdr("investigator")).status_code == 404


def test_scenario_activity_never_modifies_assessments(client, hdr, db):
    A = hdr("analyst")
    snap = lambda: [(a.id, a.updated_at, a.status) for a in db.scalars(select(Assessment))]  # noqa: E731
    before = snap()
    sc = mk(client, A)
    run(client, A, sc["id"])
    index_scenarios(client, hdr("admin"))
    db.expire_all()
    assert snap() == before
