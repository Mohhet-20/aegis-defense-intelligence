"""Deterministic fixtures analytics tests.

Window under test: W = [2026-01-10T00:00Z, 2026-01-13T00:00Z) (72 h -> hourly buckets).
The expected numbers below are derived BY HAND from the rows seeded here, never by
calling the code under test. See the comments next to each row.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.data_source import DataSource
from app.models.event import Event
from app.models.ingestion_job import IngestionJob
from app.models.observation import Observation
from app.models.raw_record import RawRecord
from app.models.sensor import Sensor

UTC = timezone.utc
W_START = datetime(2026, 1, 10, tzinfo=UTC)
W_END = datetime(2026, 1, 13, tzinfo=UTC)
WINDOW_Q = {"start": W_START.isoformat().replace("+00:00", "Z"), "end": W_END.isoformat().replace("+00:00", "Z")}


def T(day: int, h: int = 0, m: int = 0, s: int = 0) -> datetime:
    return datetime(2026, 1, day, h, m, s, tzinfo=UTC)


def mk_event(org_id, source_id, etype, observed, ingested, *, desc="d", lat=None, lon=None, lvs=None, conf=0.5, origin="user_upload", status="ingested", unc=None, title="t"):
    return Event(organization_id=org_id, source_id=source_id, event_type=etype, title=title, description=desc, observed_at=observed, ingested_at=ingested, latitude=lat, longitude=lon,
                 location_validation_status=lvs or ("valid" if lat is not None else None) or "valid", confidence=conf, data_origin=origin, processing_status=status, location_uncertainty_m=unc)


def seed(db, org, org_b):
    A = DataSource(organization_id=org.id, name="Feed A", source_type="file_upload")
    B = DataSource(organization_id=org.id, name="Feed B", source_type="file_upload")
    OB = DataSource(organization_id=org_b.id, name="Other org feed", source_type="file_upload")
    db.add_all([A, B, OB])
    db.flush()
    ev = [
        mk_event(org.id, A.id, "alert", T(10), T(10, 0, 10), lat=10.05, lon=20.05, unc=50.0),                       # e1 lag 600
        mk_event(org.id, A.id, "alert", T(11, 12, 30), T(11, 14, 30), desc="", conf=None, origin="synthetic_demo"),  # e2 lag 7200, synthetic, no desc/loc/conf
        mk_event(org.id, B.id, "movement", T(12, 23, 59, 59), T(14, 6), lat=10.06, lon=20.06, unc=150.0),          # e3 lag 108001 (late)
        mk_event(org.id, A.id, "alert", T(13), T(13, 0, 30)),                                                      # e4 at END -> outside both bases
        mk_event(org.id, A.id, "alert", T(9, 23, 59, 59), T(10, 6)),                                               # e5 before start; in window by ingestion time only
        mk_event(org.id, B.id, "movement", T(11, 5), T(11, 5, 1), status="archived"),                              # e6 archived -> excluded by default
        mk_event(org.id, A.id, "alert", T(11, 1), T(11, 1, 5), lat=95.0, lon=20.0, lvs="invalid_range"),           # e7 lag 300, invalid coordinates
        mk_event(org.id, B.id, "movement", T(12, 3), T(12, 3, 1), lat=10.07, lon=20.07),                          # e8 lag 60
        mk_event(org.id, B.id, "movement", T(12, 10), T(13, 2), lat=10.08, lon=20.08),                            # e9 lag 57600; ingested after window end
        mk_event(org.id, A.id, "alert", T(11, 3), T(11, 3, 2), lat=50.55, lon=60.55),                              # e10 lag 120, alone in its grid cell
        mk_event(org_b.id, OB.id, "alert", T(11), T(11, 0, 1)),                                                    # other organization
    ]
    db.add_all(ev)
    s1 = Sensor(organization_id=org.id, name="S1", sensor_type="thermal", lifecycle_status="active", nominal_sampling_interval_seconds=3600, category="env")
    s2 = Sensor(organization_id=org.id, name="S2", sensor_type="thermal", lifecycle_status="active", category="env")
    s3 = Sensor(organization_id=org.id, name="S3", sensor_type="thermal", lifecycle_status="retired", category="env")
    s4 = Sensor(organization_id=org.id, name="S4", sensor_type="thermal", lifecycle_status="active", nominal_sampling_interval_seconds=600, category="acoustic")
    sb = Sensor(organization_id=org_b.id, name="SB", sensor_type="thermal", lifecycle_status="active", nominal_sampling_interval_seconds=60)
    db.add_all([s1, s2, s3, s4, sb])
    db.flush()
    obs = []
    for i in range(36):  # S1: 36 hourly observations; expected 72 -> coverage 0.5
        obs.append(Observation(organization_id=org.id, sensor_id=s1.id, source_id=A.id, observed_at=T(10) + timedelta(hours=i), ingested_at=T(10) + timedelta(hours=i, seconds=5),
                               observation_type="temperature", measurement_value=None if i < 2 else 20.0 + i, validation_status="invalid" if 2 <= i < 6 else "valid", data_origin="user_upload"))
    for i in range(5):   # S2: 5 observations
        obs.append(Observation(organization_id=org.id, sensor_id=s2.id, source_id=A.id, observed_at=T(11, i), ingested_at=T(11, i, 1), observation_type="humidity", measurement_value=50.0,
                               validation_status="valid", data_origin="user_upload"))
    obs.append(Observation(organization_id=org.id, sensor_id=s1.id, source_id=A.id, observed_at=T(13), ingested_at=T(13, 0, 1), observation_type="temperature", measurement_value=1.0,
                           validation_status="valid", data_origin="user_upload"))  # at END: excluded
    obs.append(Observation(organization_id=org_b.id, sensor_id=sb.id, observed_at=T(11), ingested_at=T(11, 0, 1), observation_type="temperature", measurement_value=1.0, validation_status="valid", data_origin="user_upload"))
    db.add_all(obs)
    jobs = []
    def job(src, status, acc, rej, dup, secs, day=11, skp=0):
        jobs.append(IngestionJob(organization_id=org.id, source_id=src.id, job_type="file", status=status, started_at=T(day, len(jobs) % 20), completed_at=T(day, len(jobs) % 20) + timedelta(seconds=secs) if status != "running" else None,
                                 accepted_count=acc, rejected_count=rej, duplicate_count=dup, skipped_count=skp))
    for _ in range(6): job(A, "completed", 10, 0, 2, 60)
    for _ in range(3): job(B, "completed", 10, 0, 2, 60)
    for _ in range(2): job(A, "completed_with_errors", 5, 5, 0, 60)
    job(A, "failed", 0, 0, 0, 120)
    job(A, "running", 0, 0, 0, 0)
    jobs.append(IngestionJob(organization_id=org.id, source_id=A.id, job_type="file", status="completed", started_at=T(13), completed_at=T(13, 0, 1), accepted_count=99, rejected_count=0, duplicate_count=0, skipped_count=0))  # at END
    db.add_all(jobs)
    for i in range(10):
        db.add(RawRecord(organization_id=org.id, source_id=A.id, connector_type="file", connector_version="1", normalization_version="1", schema_version="1", content_fingerprint=f"fp{i}", payload={}, received_at=T(11, i), validation_status="invalid" if i < 2 else "valid", is_duplicate=2 <= i < 5))
    db.commit()
    return {"A": A.id, "B": B.id, "OB": OB.id, "s1": s1.id, "s2": s2.id, "s4": s4.id}


# ---- expected values, derived by hand from seed() ------------------------------------------
EVENTS_EVENT_BASIS = 7      # e1 e2 e3 e7 e8 e9 e10 (e4 at end, e5 before, e6 archived excluded)
EVENTS_INGEST_BASIS = 6     # e1 e2 e5 e7 e8 e10 (e3 and e9 ingested after the window; e4 at end)
EVENT_LAGS_SORTED = [60, 120, 300, 600, 7200, 57600, 108001]
OBS_IN_WINDOW = 41          # 36 + 5 (the one at exactly END and other-org rows excluded)
OBS_NOT_USABLE = 4
OBS_MISSING_VALUE = 2
JOBS_IN_WINDOW = 13         # 6+3 completed, 2 cwe, 1 failed, 1 running (the one starting at END excluded)
FINISHED_JOBS = 12
