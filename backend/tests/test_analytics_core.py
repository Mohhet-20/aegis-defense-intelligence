"""Phase 16: analytics correctness against hand-derived fixtures."""
from __future__ import annotations

import pytest

from tests.analytics_fixtures import (EVENT_LAGS_SORTED, EVENTS_EVENT_BASIS, EVENTS_INGEST_BASIS, FINISHED_JOBS, JOBS_IN_WINDOW, OBS_IN_WINDOW, OBS_MISSING_VALUE, OBS_NOT_USABLE,
                                      WINDOW_Q, seed)

BASE = "/api/v1/reporting"


@pytest.fixture()
def H(auth_header, tokens):
    return lambda role: auth_header(tokens, role)


@pytest.fixture()
def data(db, org, org_b):
    return seed(db, org, org_b)


def get(client, H, section, **q):
    r = client.get(f"{BASE}/analytics/{section}", params={**WINDOW_Q, **q}, headers=H("analyst"))
    assert r.status_code == 200, r.text
    return r.json()


def rows(env, tid):
    return {r[0]: r[1:] for r in env["tables"][tid]["rows"]}


def test_events_counts_event_vs_ingestion_basis(client, H, data):
    ev = get(client, H, "events")
    assert ev["values"]["events.count"]["value"] == EVENTS_EVENT_BASIS
    ing = get(client, H, "events", time_basis="ingestion")
    assert ing["values"]["events.count"]["value"] == EVENTS_INGEST_BASIS
    assert ev["window"]["time_basis"] == "event" and ing["window"]["time_basis"] == "ingestion"
    assert ev["window"]["interval"] == "start <= t < end"


def test_window_end_is_exclusive_and_start_inclusive(client, H, data):
    env = get(client, H, "events")
    buckets = rows(env, "events_by_bucket")
    assert buckets["2026-01-10T00:00:00Z"] == [1]       # e1 exactly at start is inside
    assert "2026-01-13T00:00:00Z" not in buckets         # e4 exactly at end is the next window
    assert sum(v[0] for v in buckets.values()) == EVENTS_EVENT_BASIS
    assert len(buckets) == 72                            # zero-filled hourly buckets


def test_archived_excluded_unless_requested(client, H, data):
    assert get(client, H, "events")["values"]["events.count"]["value"] == EVENTS_EVENT_BASIS
    assert get(client, H, "events", include_archived=True)["values"]["events.count"]["value"] == EVENTS_EVENT_BASIS + 1


def test_event_breakdowns_and_filters(client, H, data):
    env = get(client, H, "events")
    assert rows(env, "events_by_category") == {"alert": [4], "movement": [3]}
    assert rows(env, "events_by_source") == {"Feed A": [4], "Feed B": [3]}
    assert rows(env, "events_by_data_origin") == {"user_upload": [6], "synthetic_demo": [1]}
    filt = get(client, H, "events", category="movement")
    assert filt["values"]["events.count"]["value"] == 3 and filt["filters"]["category"] == "movement"
    filt = get(client, H, "events", source_id=data["A"])
    assert filt["values"]["events.count"]["value"] == 4


def test_event_data_quality_rates_and_lag(client, H, data):
    v = get(client, H, "events")["values"]
    assert v["events.synthetic_share"]["value"] == pytest.approx(1 / 7, abs=1e-4)
    assert v["events.missing_description_rate"]["value"] == pytest.approx(1 / 7, abs=1e-4)
    assert v["events.missing_location_rate"]["value"] == pytest.approx(1 / 7, abs=1e-4)
    assert v["events.invalid_location_rate"]["value"] == pytest.approx(1 / 6, abs=1e-4)  # denominator = events WITH coordinates
    assert v["events.missing_confidence_rate"]["value"] == pytest.approx(1 / 7, abs=1e-4)
    assert v["events.late_arrival_rate"]["value"] == pytest.approx(1 / 7, abs=1e-4)
    assert v["events.ingestion_lag_p50_seconds"]["value"] == EVENT_LAGS_SORTED[3]
    assert v["events.ingestion_lag_p95_seconds"]["value"] == EVENT_LAGS_SORTED[6]


def test_other_organization_data_never_counted(client, H, data):
    env = get(client, H, "events", category="alert")
    assert env["values"]["events.count"]["value"] == 4  # the org-B alert in the same window is excluded
    assert "Other org feed" not in str(env)


def test_missing_is_not_zero_for_empty_denominators(client, H, data):
    env = get(client, H, "events", category="does_not_exist")
    assert env["status"] == "empty"
    r = env["values"]["events.missing_description_rate"]
    assert r["value"] is None and r["reason"] == "no_records_in_window"
    assert env["values"]["events.count"]["value"] == 0   # a count of stored rows IS a true zero
    assert any("does not distinguish" in c or "not" in c for c in env["caveats"])


def test_observations_section(client, H, data):
    env = get(client, H, "observations")
    v = env["values"]
    assert v["observations.count"]["value"] == OBS_IN_WINDOW
    assert v["observations.not_usable_rate"]["value"] == pytest.approx(OBS_NOT_USABLE / OBS_IN_WINDOW, abs=1e-4)
    assert v["observations.missing_value_rate"]["value"] == pytest.approx(OBS_MISSING_VALUE / OBS_IN_WINDOW, abs=1e-4)
    assert rows(env, "observations_by_type") == {"temperature": [36], "humidity": [5]}
    assert rows(env, "observations_by_validation_status") == {"valid": [37], "invalid": [4]}
    assert "observations_by_sensor" in env["tables"]


def test_ingestion_rates_and_minimum_denominator(client, H, data):
    env = get(client, H, "ingestion")
    v = env["values"]
    assert v["ingestion.jobs_count"]["value"] == JOBS_IN_WINDOW
    assert v["ingestion.failure_rate"]["value"] == pytest.approx(1 / FINISHED_JOBS, abs=1e-4)
    assert v["ingestion.partial_rate"]["value"] == pytest.approx(2 / FINISHED_JOBS, abs=1e-4)
    assert v["ingestion.records_accepted"]["value"] == 9 * 10 + 2 * 5
    assert v["ingestion.records_rejected"]["value"] == 10
    assert v["ingestion.records_duplicate"]["value"] == 9 * 2
    assert v["ingestion.duration_p50_seconds"]["value"] == 60
    assert v["ingestion.raw_records"]["value"] == 10
    assert v["ingestion.raw_invalid_rate"]["value"] == pytest.approx(0.2)
    assert v["ingestion.raw_duplicate_rate"]["value"] == pytest.approx(0.3)
    small = get(client, H, "ingestion", source_id=data["B"])  # 3 finished jobs < minimum of 10
    f = small["values"]["ingestion.failure_rate"]
    assert f["value"] is None and f["reason"].startswith("insufficient_sample")
    assert small["values"]["ingestion.jobs_count"]["value"] == 3


def test_sensor_coverage_is_data_coverage_and_null_without_interval(client, H, data):
    env = get(client, H, "sensors")
    cov = {r[0]: r for r in env["tables"]["sensor_coverage"]["rows"]}
    assert cov["S1"][5] == pytest.approx(0.5)              # 36 observations / 72 expected
    assert cov["S2"][5] is None                            # no nominal interval -> null, not zero
    assert cov["S4"][3] == 0 and cov["S4"][5] == 0.0       # configured and silent
    assert "S3" not in cov                                 # retired sensors are not expected to report
    assert env["values"]["sensors.silent_count"]["value"] == 1
    assert any("not uptime" in c for c in env["caveats"]) or any("uptime" in c for c in env["caveats"])


def test_geo_suppresses_small_cells_and_never_returns_coordinates(client, H, data):
    env = get(client, H, "geo")
    cells = env["tables"]["grid_cells"]["rows"]
    assert len(cells) == 1 and cells[0][3] == 4            # e1,e3,e8,e9 share a 0.1 degree cell; e10's cell (1 record) is suppressed
    assert env["sample_counts"]["cells_suppressed"] == 1 and env["sample_counts"]["records_in_suppressed_cells"] == 1
    flat = str(env)
    for raw in ("10.05", "20.05", "50.55", "60.55", "10.08"):
        assert raw not in flat
    status = {r[0]: r for r in env["tables"]["coordinate_status"]["rows"]}
    assert status["events"][4] == 1                        # e7: invalid_range
    assert env["values"]["geo.median_uncertainty_m"]["value"] in (50.0, 150.0)
    assert any("never individual coordinates" in c for c in env["caveats"])


def test_every_emitted_metric_is_catalogued(client, H, data):
    from app.reporting import definitions as d

    ids = set()
    for sec in ("events", "observations", "ingestion", "fusion", "sensors", "investigations", "evidence", "models", "system", "geo", "review_backlog"):
        env = get(client, H, sec)
        ids |= set(env["values"])
        for t in env["tables"].values():
            ids |= set(t["metric_ids"])
    assert ids and ids <= set(d.CATALOG)
    for mid, m in d.CATALOG.items():
        assert m["definition"] and m["unit"] and m["section"] in d.SECTION_IDS


def test_window_validation_rejects_bad_input(client, H, data):
    h = H("analyst")
    for q in ({"start": "2026-01-13T00:00:00Z", "end": "2026-01-10T00:00:00Z"}, {"days": 400}, {"start": "2025-01-01T00:00:00Z", "end": "2026-06-01T00:00:00Z"},
              {"start": "2026-01-10T00:00:00Z"}, {"days": 3, "start": "2026-01-10T00:00:00Z", "end": "2026-01-11T00:00:00Z"}, {"bucket": "week"}, {"time_basis": "wall"},
              {"start": "2026-01-01T00:00:00Z", "end": "2026-01-30T00:00:00Z", "bucket": "hour"}):
        r = client.get(f"{BASE}/analytics/events", params=q, headers=h)
        assert r.status_code == 422, (q, r.text)
    assert client.get(f"{BASE}/analytics/events", params={"source_id": "x" * 101}, headers=h).status_code == 422
    assert client.get(f"{BASE}/analytics/nope", headers=h).status_code == 404
