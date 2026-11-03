"""Analytics sections.

Rules every section follows:
* organization_id comes from the authenticated user and is applied in the query
  BEFORE any aggregation; sections the caller may not read return `not_authorized`
  with no counts at all.
* Windows are half-open UTC; the time basis (event vs ingestion) is explicit.
* Queries are bounded: grouped SQL aggregates, or a fetch capped at ANALYTICS_MAX_ROWS
  (with a `truncated` caveat) where a percentile needs raw values.
* Missing is not zero: a rate with no denominator is null with a reason.
* Associations are described as associations; anomalies/volume changes are
  prompts for review and never evidence of malicious activity.
"""
from __future__ import annotations

import math
from typing import Callable

from sqlalchemy import and_, case, func, or_, select

from app.core.config import get_settings
from app.core.security import Permission, Role
from app.models.conflict import Conflict
from app.models.data_source import DataSource
from app.models.event import Event
from app.models.event_correlation import EventCorrelation
from app.models.evidence import Evidence
from app.models.evidence_relationship import EvidenceRelationship
from app.models.fusion_job import FusionJob
from app.models.ingestion_job import IngestionJob
from app.models.observation import Observation
from app.models.raw_record import RawRecord
from app.reporting import definitions as defs
from app.reporting.envelope import Ctx, Section, not_authorized
from app.reporting.window import AnalyticsWindow, as_utc, percentile

TOP_N = 20


# ------------------------------------------------------------------ helpers ---
def bucket_expr(col, bucket: str, db):
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        # to_char() on a timestamptz formats in the *session* TimeZone, which is whatever
        # the server's postgresql.conf says (initdb copies the OS zone). Convert to UTC
        # first so bucket labels match the UTC window on any server.
        return func.to_char(func.timezone("UTC", col), 'YYYY-MM-DD"T"HH24:00:00"Z"' if bucket == "hour" else "YYYY-MM-DD")
    return func.strftime("%Y-%m-%dT%H:00:00Z" if bucket == "hour" else "%Y-%m-%d", col)


def in_window(col, w: AnalyticsWindow):
    return and_(col >= w.start, col < w.end)


def series(ctx: Ctx, tcol, where: list, extra_group=None) -> list[list]:
    """Zero-filled [bucket, count] rows. Zero == no stored records with that timestamp."""
    b = bucket_expr(tcol, ctx.window.bucket, ctx.db)
    got = {k: n for k, n in ctx.db.execute(select(b, func.count()).where(*where, in_window(tcol, ctx.window)).group_by(b)).all()}
    return [[lab, int(got.get(lab, 0))] for lab in ctx.window.bucket_labels()]


def top_counts(ctx: Ctx, col, where: list, total: int) -> list[list]:
    rows = ctx.db.execute(select(col, func.count().label("n")).where(*where).group_by(col).order_by(func.count().desc(), col).limit(TOP_N)).all()
    out = [[("(none)" if k is None else str(k)), int(n)] for k, n in rows]
    rest = total - sum(r[1] for r in out)
    if rest > 0:
        out.append(["other", rest])
    return out


def _lag_stats(ctx: Ctx, model, where: list) -> tuple[list[float], bool, int]:
    cap = get_settings().ANALYTICS_MAX_ROWS
    rows = ctx.db.execute(select(model.observed_at, model.ingested_at).where(*where).order_by(model.ingested_at.desc(), model.id).limit(cap + 1)).all()
    truncated = len(rows) > cap
    lags = sorted((as_utc(i) - as_utc(o)).total_seconds() for o, i in rows[:cap] if o is not None and i is not None)
    return lags, truncated, min(len(rows), cap)


def _source_names(ctx: Ctx) -> dict[str, str]:
    return {i: n for i, n in ctx.db.execute(select(DataSource.id, DataSource.name).where(DataSource.organization_id == ctx.org)).all()}


def _tcol(model, ctx: Ctx):
    return model.observed_at if ctx.window.time_basis == "event" else model.ingested_at


def _basis_caveat(sec: Section, ctx: Ctx) -> None:
    if ctx.window.time_basis == "event":
        sec.caveat("Windowed by event time (observed_at as reported by the source). Records ingested late appear in the window they describe, so recent windows can still grow.")
    else:
        sec.caveat("Windowed by ingestion time (when AEGIS stored the record). The event times inside a bucket may be much older.")


# ------------------------------------------------------------------- events ---
def events_section(ctx: Ctx) -> dict:
    if not ctx.can(Permission.EVENT_READ):
        return not_authorized("events", ctx, "event:read")
    sec = Section("events", ctx)
    f, db = ctx.filters, ctx.db
    tcol = _tcol(Event, ctx)
    base = [Event.organization_id == ctx.org]
    if f.source_id:
        base.append(Event.source_id == f.source_id)
    if f.category:
        base.append(Event.event_type == f.category)
    if not f.include_archived:
        base.append(Event.processing_status != "archived")
    where = base + [in_window(tcol, ctx.window)]
    n = db.scalar(select(func.count()).select_from(Event).where(*where)) or 0
    sec.sample_counts = {"events": n}
    sec.value("events.count", n, n)
    sec.freshness_from(db.scalar(select(func.max(Event.ingested_at)).where(*base)), "latest_ingested_at")
    _basis_caveat(sec, ctx)
    sec.caveat("Counts describe stored records only. A zero bucket means no stored event had that timestamp; it does not distinguish a quiet period from data that was never received. Changes in volume are not evidence of malicious activity.")
    if n == 0:
        sec.status = "empty"
    sec.table("events_by_bucket", "events.by_bucket", f"Events per {ctx.window.bucket} ({ctx.window.time_basis} time, UTC)", ["bucket", "events"], series(ctx, tcol, base))
    sec.table("events_by_category", "events.by_category", "Events by category", ["category", "events"], top_counts(ctx, Event.event_type, where, n))
    names = _source_names(ctx)
    src = top_counts(ctx, Event.source_id, where, n)
    sec.table("events_by_source", "events.by_source", "Events by source", ["source", "events"], [[names.get(r[0], r[0]) if r[0] not in ("other", "(none)") else r[0], r[1]] for r in src])
    sec.table("events_by_processing_status", "events.by_processing_status", "Events by processing status", ["status", "events"], top_counts(ctx, Event.processing_status, where, n))
    origins = top_counts(ctx, Event.data_origin, where, n)
    sec.table("events_by_data_origin", "events.by_data_origin", "Events by data origin", ["data_origin", "events"], origins)
    synth = next((r[1] for r in origins if r[0] == "synthetic_demo"), 0)
    sec.rate("events.synthetic_share", synth, n)
    if synth:
        sec.caveat(f"{synth} of {n} events are synthetic demonstration data and must not be read as real-world activity.")
    # missing-field rates (aggregated in SQL)
    agg = db.execute(select(
        func.sum(case((or_(Event.description.is_(None), Event.description == ""), 1), else_=0)),
        func.sum(case((or_(Event.latitude.is_(None), Event.longitude.is_(None)), 1), else_=0)),
        func.sum(case((and_(Event.latitude.isnot(None), Event.longitude.isnot(None)), 1), else_=0)),
        func.sum(case((and_(Event.latitude.isnot(None), Event.longitude.isnot(None), Event.location_validation_status != "valid"), 1), else_=0)),
        func.sum(case((Event.confidence.is_(None), 1), else_=0)),
    ).where(*where)).one()
    nd, nl, with_loc, bad_loc, nc = (int(x or 0) for x in agg)
    sec.rate("events.missing_description_rate", nd, n)
    sec.rate("events.missing_location_rate", nl, n)
    sec.rate("events.invalid_location_rate", bad_loc, with_loc)
    sec.rate("events.missing_confidence_rate", nc, n)
    lags, trunc, m = _lag_stats(ctx, Event, where)
    late_after = get_settings().ANALYTICS_LATE_ARRIVAL_HOURS * 3600
    sec.rate("events.late_arrival_rate", sum(1 for x in lags if x > late_after), len(lags))
    sec.value("events.ingestion_lag_p50_seconds", percentile(lags, 0.5), len(lags), "no_records_in_window")
    sec.value("events.ingestion_lag_p95_seconds", percentile(lags, 0.95), len(lags), "no_records_in_window")
    skew = sum(1 for x in lags if x < 0)
    if skew:
        sec.caveat(f"{skew} event(s) have an event time later than their ingestion time (source clock ahead); they are included in lag percentiles as negative values.")
    if trunc:
        sec.caveat(f"Lag statistics use only the {m} most recently ingested events in the window (limit ANALYTICS_MAX_ROWS); they are partial.")
        sec.status = "partial"
    sec.drilldown = {"events.by_category": "/events?event_type={value}", "events.by_data_origin": "/events?data_origin={value}", "events.count": "/events"}
    return sec.build()


# ------------------------------------------------------------- observations ---
def observations_section(ctx: Ctx) -> dict:
    if not ctx.can(Permission.OBSERVATION_READ):
        return not_authorized("observations", ctx, "observation:read")
    sec = Section("observations", ctx)
    f, db = ctx.filters, ctx.db
    tcol = _tcol(Observation, ctx)
    base = [Observation.organization_id == ctx.org]
    if f.source_id:
        base.append(Observation.source_id == f.source_id)
    if f.category:
        base.append(Observation.observation_type == f.category)
    where = base + [in_window(tcol, ctx.window)]
    n = db.scalar(select(func.count()).select_from(Observation).where(*where)) or 0
    sec.sample_counts = {"observations": n}
    sec.value("observations.count", n, n)
    sec.freshness_from(db.scalar(select(func.max(Observation.ingested_at)).where(*base)), "latest_ingested_at")
    _basis_caveat(sec, ctx)
    sec.caveat("Counts describe stored observations only; zero means none stored, not that a sensor was inactive.")
    if n == 0:
        sec.status = "empty"
    sec.table("observations_by_bucket", "observations.by_bucket", f"Observations per {ctx.window.bucket} ({ctx.window.time_basis} time, UTC)", ["bucket", "observations"], series(ctx, tcol, base))
    sec.table("observations_by_type", "observations.by_type", "Observations by type", ["observation_type", "observations"], top_counts(ctx, Observation.observation_type, where, n))
    vs = top_counts(ctx, Observation.validation_status, where, n)
    sec.table("observations_by_validation_status", "observations.by_validation_status", "Observations by validation status", ["validation_status", "observations"], vs)
    from app.models.sensor import Sensor
    snames = {i: nm for i, nm in db.execute(select(Sensor.id, Sensor.name).where(Sensor.organization_id == ctx.org)).all()}
    rows = db.execute(select(Observation.sensor_id, func.count()).where(*where).group_by(Observation.sensor_id).order_by(func.count().desc(), Observation.sensor_id).limit(TOP_N)).all()
    srows = [[snames.get(k, k or "(none)"), int(c)] for k, c in rows]
    if n - sum(r[1] for r in srows) > 0:
        srows.append(["other", n - sum(r[1] for r in srows)])
    sec.table("observations_by_sensor", "observations.by_sensor", "Observations by sensor (volume only, not a quality ranking)", ["sensor", "observations"], srows)
    usable = ("valid", "valid_with_warnings")
    bad = db.scalar(select(func.count()).select_from(Observation).where(*where, Observation.validation_status.notin_(usable))) or 0
    sec.rate("observations.not_usable_rate", bad, n)
    miss = db.scalar(select(func.count()).select_from(Observation).where(*where, Observation.measurement_value.is_(None))) or 0
    sec.rate("observations.missing_value_rate", miss, n)
    lags, trunc, m = _lag_stats(ctx, Observation, where)
    late_after = get_settings().ANALYTICS_LATE_ARRIVAL_HOURS * 3600
    sec.rate("observations.late_arrival_rate", sum(1 for x in lags if x > late_after), len(lags))
    sec.value("observations.ingestion_lag_p50_seconds", percentile(lags, 0.5), len(lags), "no_records_in_window")
    sec.value("observations.ingestion_lag_p95_seconds", percentile(lags, 0.95), len(lags), "no_records_in_window")
    if trunc:
        sec.caveat(f"Lag statistics use only the {m} most recently ingested observations in the window; they are partial.")
        sec.status = "partial"
    sec.drilldown = {"observations.count": "/sensors/ingestion"}
    return sec.build()


# --------------------------------------------------------------- ingestion ---
FINISHED = ("completed", "completed_with_errors", "failed")


def ingestion_section(ctx: Ctx) -> dict:
    if not ctx.can(Permission.DATA_QUALITY_READ):
        return not_authorized("ingestion", ctx, "data_quality:read")
    sec = Section("ingestion", ctx)
    db, f, s = ctx.db, ctx.filters, get_settings()
    jbase = [IngestionJob.organization_id == ctx.org]
    if f.source_id:
        jbase.append(IngestionJob.source_id == f.source_id)
    jwhere = jbase + [in_window(IngestionJob.started_at, ctx.window)]
    n = db.scalar(select(func.count()).select_from(IngestionJob).where(*jwhere)) or 0
    sec.value("ingestion.jobs_count", n, n)
    by_status = dict(db.execute(select(IngestionJob.status, func.count()).where(*jwhere).group_by(IngestionJob.status)).all())
    sec.table("jobs_by_status", "ingestion.by_status", "Ingestion jobs by status (job start time)", ["status", "jobs"], [[k, int(v)] for k, v in sorted(by_status.items())])
    # per-bucket split by outcome
    b = bucket_expr(IngestionJob.started_at, ctx.window.bucket, db)
    got: dict[str, dict] = {}
    for lab, st, c in db.execute(select(b, IngestionJob.status, func.count()).where(*jwhere).group_by(b, IngestionJob.status)).all():
        got.setdefault(lab, {})[st] = int(c)
    sec.table("jobs_by_bucket", "ingestion.by_bucket", f"Ingestion jobs per {ctx.window.bucket} by outcome (UTC)", ["bucket", "completed", "completed_with_errors", "failed", "other"],
              [[lab, got.get(lab, {}).get("completed", 0), got.get(lab, {}).get("completed_with_errors", 0), got.get(lab, {}).get("failed", 0),
                sum(v for k, v in got.get(lab, {}).items() if k not in FINISHED)] for lab in ctx.window.bucket_labels()])
    finished = sum(by_status.get(k, 0) for k in FINISHED)
    sec.rate("ingestion.failure_rate", by_status.get("failed", 0), finished, s.ANALYTICS_MIN_FINISHED_JOBS)
    sec.rate("ingestion.partial_rate", by_status.get("completed_with_errors", 0), finished, s.ANALYTICS_MIN_FINISHED_JOBS)
    cap = s.ANALYTICS_MAX_ROWS
    drows = db.execute(select(IngestionJob.started_at, IngestionJob.completed_at).where(*jwhere, IngestionJob.status.in_(FINISHED), IngestionJob.completed_at.isnot(None))
                       .order_by(IngestionJob.started_at.desc()).limit(cap + 1)).all()
    durs = sorted((as_utc(c) - as_utc(st)).total_seconds() for st, c in drows[:cap])
    sec.value("ingestion.duration_p50_seconds", percentile(durs, 0.5), len(durs), "no_finished_jobs_with_completion_time")
    sec.value("ingestion.duration_p95_seconds", percentile(durs, 0.95), len(durs), "no_finished_jobs_with_completion_time")
    if len(drows) > cap:
        sec.caveat("Duration percentiles use only the most recent jobs (ANALYTICS_MAX_ROWS); they are partial.")
        sec.status = "partial"
    sums = db.execute(select(func.coalesce(func.sum(IngestionJob.accepted_count), 0), func.coalesce(func.sum(IngestionJob.rejected_count), 0),
                             func.coalesce(func.sum(IngestionJob.skipped_count), 0), func.coalesce(func.sum(IngestionJob.duplicate_count), 0)).where(*jwhere)).one()
    acc, rej, skp, dup = (int(x) for x in sums)
    sec.value("ingestion.records_accepted", acc, n)
    sec.value("ingestion.records_rejected", rej, n)
    sec.value("ingestion.records_skipped", skp, n)
    sec.value("ingestion.records_duplicate", dup, n)
    sec.rate("ingestion.duplicate_rate", dup, acc + rej + skp + dup)
    # per-source table incl. recorded last success
    names = _source_names(ctx)
    last = {i: (a, sc, err) for i, a, sc, err in db.execute(select(DataSource.id, DataSource.last_ingestion_attempt_at, DataSource.last_ingestion_success_at, DataSource.last_error_category)
                                                              .where(DataSource.organization_id == ctx.org)).all()}
    prow = db.execute(select(IngestionJob.source_id, func.count(), func.sum(case((IngestionJob.status == "failed", 1), else_=0)),
                             func.coalesce(func.sum(IngestionJob.accepted_count), 0), func.coalesce(func.sum(IngestionJob.rejected_count), 0))
                      .where(*jwhere).group_by(IngestionJob.source_id).order_by(func.count().desc(), IngestionJob.source_id).limit(TOP_N)).all()
    sec.table("jobs_by_source", "ingestion.by_source", "Ingestion by source (job start time)",
              ["source", "jobs", "failed", "accepted", "rejected", "last_success_at", "last_error_category"],
              [[names.get(sid, sid or "(none)"), int(c), int(fl or 0), int(a), int(r), (last.get(sid, (None, None, None))[1].isoformat() if last.get(sid, (None, None, None))[1] else None), last.get(sid, (None, None, None))[2]] for sid, c, fl, a, r in prow])
    # raw records
    rbase = [RawRecord.organization_id == ctx.org]
    if f.source_id:
        rbase.append(RawRecord.source_id == f.source_id)
    rwhere = rbase + [in_window(RawRecord.received_at, ctx.window)]
    rn, rinv, rdup = db.execute(select(func.count(), func.sum(case((RawRecord.validation_status == "invalid", 1), else_=0)), func.sum(case((RawRecord.is_duplicate.is_(True), 1), else_=0))).where(*rwhere)).one()
    rn, rinv, rdup = int(rn or 0), int(rinv or 0), int(rdup or 0)
    sec.value("ingestion.raw_records", rn, rn)
    sec.rate("ingestion.raw_invalid_rate", rinv, rn)
    sec.rate("ingestion.raw_duplicate_rate", rdup, rn)
    sec.sample_counts = {"jobs": n, "finished_jobs": finished, "raw_records": rn}
    sec.freshness_from(db.scalar(select(func.max(DataSource.last_ingestion_success_at)).where(DataSource.organization_id == ctx.org, *( [DataSource.id == f.source_id] if f.source_id else []))), "latest_source_success_at")
    sec.caveat("Windowed by job start time (jobs) and received time (raw records) regardless of the event/ingestion time basis chosen elsewhere.")
    sec.caveat("Rates are not reported (null) when fewer than the minimum number of finished jobs exist; a rate from a handful of jobs is not meaningful.")
    sec.caveat("Duplicates are expected with overlapping pulls and are not a fault by themselves.")
    if n == 0 and rn == 0:
        sec.status = "empty"
    sec.drilldown = {"ingestion.by_status": "/ingestion", "ingestion.jobs_count": "/ingestion", "ingestion.raw_invalid_rate": "/data-quality"}
    return sec.build()


# ------------------------------------------------------------------- fusion ---
def _grouped(ctx: Ctx, col, where: list) -> list[list]:
    return [[("(none)" if k is None else str(k)), int(c)] for k, c in ctx.db.execute(select(col, func.count()).where(*where).group_by(col).order_by(col)).all()]


def fusion_section(ctx: Ctx) -> dict:
    if not ctx.can(Permission.FUSION_READ):
        return not_authorized("fusion", ctx, "fusion:read")
    sec = Section("fusion", ctx)
    db, w = ctx.db, ctx.window
    cw = [EventCorrelation.organization_id == ctx.org, in_window(EventCorrelation.created_at, w)]
    sec.table("correlations_by_review_status", "fusion.correlations_by_review_status", "Correlation candidates by review status (created in window)", ["review_status", "correlations"], _grouped(ctx, EventCorrelation.review_status, cw))
    rw = [EvidenceRelationship.organization_id == ctx.org, in_window(EvidenceRelationship.created_at, w)]
    rows = db.execute(select(EvidenceRelationship.relationship_type, EvidenceRelationship.origin, func.count()).where(*rw).group_by(EvidenceRelationship.relationship_type, EvidenceRelationship.origin)
                      .order_by(EvidenceRelationship.relationship_type, EvidenceRelationship.origin)).all()
    sec.table("relationships_by_type_origin", "fusion.relationships_by_type_origin", "Evidence relationships by type and origin (created in window)", ["relationship_type", "origin", "relationships"], [[a, b, int(c)] for a, b, c in rows])
    total = sum(int(r[2]) for r in rows)
    inferred = sum(int(r[2]) for r in rows if r[1] in ("rule_based", "model_assisted"))
    sec.rate("fusion.relationships_inferred_share", inferred, total)
    cfw = [Conflict.organization_id == ctx.org, in_window(Conflict.created_at, w)]
    sec.table("conflicts_by_status", "fusion.conflicts_by_status", "Conflicts by review status (created in window)", ["review_status", "conflicts"], _grouped(ctx, Conflict.review_status, cfw))
    unresolved = db.scalar(select(func.count()).select_from(Conflict).where(Conflict.organization_id == ctx.org, Conflict.review_status == "unresolved")) or 0
    sec.value("fusion.conflicts_unresolved", unresolved, unresolved)
    jw = [FusionJob.organization_id == ctx.org, in_window(FusionJob.started_at, w)]
    sec.table("fusion_jobs_by_status", "fusion.jobs_by_status", "Fusion jobs by status (start time)", ["status", "jobs"], _grouped(ctx, FusionJob.status, jw))
    cap = get_settings().ANALYTICS_MAX_ROWS
    rr = db.execute(select(EventCorrelation.created_at, EventCorrelation.reviewed_at).where(EventCorrelation.organization_id == ctx.org, EventCorrelation.reviewed_at.isnot(None),
                                                                                              in_window(EventCorrelation.reviewed_at, w)).limit(cap + 1)).all()
    ttr = sorted((as_utc(r) - as_utc(c)).total_seconds() for c, r in rr[:cap])
    sec.value("fusion.time_to_review_p50_seconds", percentile(ttr, 0.5), len(ttr), "no_correlations_reviewed_in_window")
    ncorr = sum(r[1] for r in sec.tables["correlations_by_review_status"]["rows"])
    sec.sample_counts = {"correlations": ncorr, "relationships": total, "conflicts": sum(r[1] for r in sec.tables["conflicts_by_status"]["rows"]),
                         "fusion_jobs": sum(r[1] for r in sec.tables["fusion_jobs_by_status"]["rows"])}
    sec.freshness_from(db.scalar(select(func.max(FusionJob.finished_at)).where(FusionJob.organization_id == ctx.org, FusionJob.status == "completed")), "latest_completed_fusion_job_at")
    sec.caveat("Windowed by each record's creation (or review) time. A correlation is an association found by a rule; it is not proof of causation, identity or intent.")
    sec.caveat("Relationships with origin rule_based or model_assisted are inferred; only analyst_created relationships were explicitly recorded by a person.")
    if not any(sec.sample_counts.values()) and not unresolved:
        sec.status = "empty"
    sec.drilldown = {"fusion.conflicts_unresolved": "/fusion/conflicts", "fusion.correlations_by_review_status": "/correlation", "fusion.relationships_by_type_origin": "/fusion/relationships"}
    return sec.build()


# ------------------------------------------------------------------ sensors ---
def sensors_section(ctx: Ctx) -> dict:
    from app.models.observation_anomaly import ObservationAnomaly
    from app.models.sensor import Sensor

    if not (ctx.can(Permission.SENSOR_READ) and ctx.can(Permission.OBSERVATION_READ)):
        return not_authorized("sensors", ctx, "sensor:read and observation:read")
    sec = Section("sensors", ctx)
    db, w = ctx.db, ctx.window
    sw = [Sensor.organization_id == ctx.org]
    if ctx.filters.source_id:
        sw.append(Sensor.source_id == ctx.filters.source_id)
    sec.table("sensors_by_lifecycle_status", "sensors.by_lifecycle_status", "Sensors by lifecycle status (current)", ["lifecycle_status", "sensors"], _grouped(ctx, Sensor.lifecycle_status, sw))
    nsens = sum(r[1] for r in sec.tables["sensors_by_lifecycle_status"]["rows"])
    tcol = _tcol(Observation, ctx)
    counts = {sid: int(c) for sid, c in db.execute(select(Observation.sensor_id, func.count()).where(Observation.organization_id == ctx.org, in_window(tcol, w)).group_by(Observation.sensor_id)).all()}
    rows = db.execute(select(Sensor.id, Sensor.name, Sensor.category, Sensor.lifecycle_status, Sensor.nominal_sampling_interval_seconds).where(*sw, Sensor.lifecycle_status.in_(("active", "degraded")))
                      .order_by(Sensor.name, Sensor.id).limit(501)).all()
    capped = len(rows) > 500
    rows = rows[:500]
    cov_rows, silent, bycat = [], 0, {}
    for sid, name, cat, lc, interval in rows:
        got = counts.get(sid, 0)
        if got == 0:
            silent += 1
        expected = (w.seconds / interval) if interval and interval > 0 else None
        cov = round(min(1.0, got / expected), 4) if expected else None
        cov_rows.append([name, lc, interval, got, round(expected, 1) if expected else None, cov])
        c = bycat.setdefault(cat or "(uncategorised)", [0, 0])
        c[0] += 1
        c[1] += got
    sec.table("sensor_coverage", "sensors.coverage", "Observation coverage per active/degraded sensor (data coverage, not uptime; alphabetical, not ranked)",
              ["sensor", "lifecycle_status", "nominal_interval_s", "observations", "expected", "coverage"], cov_rows[:100], "proportion")
    if len(cov_rows) > 100:
        sec.caveat("Only the first 100 sensors (alphabetical) are listed; aggregate values cover all of them.")
    if capped:
        sec.caveat("More than 500 active/degraded sensors exist; coverage was computed for the first 500 alphabetically.")
        sec.status = "partial"
    sec.value("sensors.silent_count", silent, len(rows))
    sec.table("sensors_by_category", "sensors.by_category", "Active/degraded sensors and observations by category", ["category", "sensors", "observations"], [[k, v[0], v[1]] for k, v in sorted(bycat.items())])
    no_interval = sum(1 for r in cov_rows if r[5] is None)
    if no_interval:
        sec.caveat(f"{no_interval} sensor(s) have no nominal sampling interval configured; coverage is not computed for them (null, not zero).")
    aw = [ObservationAnomaly.organization_id == ctx.org, in_window(ObservationAnomaly.created_at, w)]
    if ctx.can(Permission.ANOMALY_READ):
        sec.table("anomalies_by_review_status", "sensors.anomalies_by_review_status", "Anomaly candidates by review status (created in window)", ["review_status", "anomalies"], _grouped(ctx, ObservationAnomaly.review_status, aw))
        sec.table("anomalies_by_severity", "sensors.anomalies_by_severity", "Anomaly candidates by severity (created in window)", ["severity", "anomalies"], _grouped(ctx, ObservationAnomaly.severity, aw))
        sec.caveat("An anomaly is a statistical flag for human review. It is not a finding, and an unusual value is not evidence of malicious activity; data-quality issues are a common cause.")
    else:
        sec.caveat("Anomaly figures omitted: they require the anomaly:read permission.")
        sec.status = "partial"
    sec.sample_counts = {"sensors": nsens, "active_or_degraded_sensors": len(rows), "observations_in_window": sum(counts.values())}
    sec.freshness_from(db.scalar(select(func.max(Sensor.last_seen_at)).where(*sw)), "latest_sensor_last_seen_at")
    sec.caveat("Coverage = observations stored in the window / observations expected from the nominal sampling interval (capped at 1). It measures stored data, not sensor uptime; AEGIS does not collect uptime telemetry.")
    sec.caveat("A silent sensor may be offline, misconfigured, or have no data stored; it is not evidence of tampering.")
    if nsens == 0:
        sec.status = "empty"
    sec.drilldown = {"sensors.coverage": "/sensors", "sensors.anomalies_by_review_status": "/sensors/anomalies"}
    return sec.build()


# ------------------------------------------------------------ investigations ---
def visible_investigation_clauses(ctx: Ctx) -> list:
    from app.models.investigation import Investigation
    from app.models.investigation_workspace import InvestigationMember

    c = [Investigation.organization_id == ctx.org]
    if ctx.user.role != Role.ADMINISTRATOR:
        c.append(or_(Investigation.is_restricted.is_(False), Investigation.assigned_user_id == ctx.user.id,
                     Investigation.id.in_(select(InvestigationMember.investigation_id).where(InvestigationMember.user_id == ctx.user.id))))
    return c


def investigations_section(ctx: Ctx) -> dict:
    from app.models.investigation import Investigation
    from app.models.investigation_workspace import InvestigationStatusHistory

    if not ctx.can(Permission.INVESTIGATION_READ):
        return not_authorized("investigations", ctx, "investigation:read")
    sec = Section("investigations", ctx)
    db, w = ctx.db, ctx.window
    vis = visible_investigation_clauses(ctx)
    sec.table("investigations_by_status", "investigations.by_status", "Investigations by status (current, visible to you)", ["status", "investigations"], _grouped(ctx, Investigation.status, vis))
    total_now = sum(r[1] for r in sec.tables["investigations_by_status"]["rows"])
    nc = db.scalar(select(func.count()).select_from(Investigation).where(*vis, in_window(Investigation.created_at, w))) or 0
    ncl = db.scalar(select(func.count()).select_from(Investigation).where(*vis, in_window(Investigation.closed_at, w))) or 0
    sec.value("investigations.created_count", nc, nc)
    sec.value("investigations.closed_count", ncl, ncl)
    sec.table("investigations_created_by_bucket", "investigations.created_by_bucket", f"Investigations created per {w.bucket} (UTC)", ["bucket", "created"], series(ctx, Investigation.created_at, vis))
    sec.table("investigations_closed_by_bucket", "investigations.closed_by_bucket", f"Investigations closed per {w.bucket} (UTC)", ["bucket", "closed"], series(ctx, Investigation.closed_at, vis))
    cap = get_settings().ANALYTICS_MAX_ROWS
    cl = db.execute(select(Investigation.created_at, Investigation.closed_at).where(*vis, in_window(Investigation.closed_at, w)).limit(cap)).all()
    days = sorted((as_utc(c2) - as_utc(c1)).total_seconds() / 86400 for c1, c2 in cl)
    sec.value("investigations.time_to_close_p50_days", round(percentile(days, 0.5), 3) if days else None, len(days), "no_investigations_closed_in_window")
    openw = vis + [Investigation.status.notin_(("closed", "archived"))]
    sec.table("investigations_by_priority", "investigations.by_priority", "Open investigations by priority (current)", ["priority", "investigations"], _grouped(ctx, Investigation.priority, openw))
    hw = [InvestigationStatusHistory.organization_id == ctx.org, in_window(InvestigationStatusHistory.created_at, w),
          InvestigationStatusHistory.investigation_id.in_(select(Investigation.id).where(*vis))]
    sec.table("investigations_transitions", "investigations.transitions", "Status transitions by target status (in window)", ["to_status", "transitions"], _grouped(ctx, InvestigationStatusHistory.to_status, hw))
    if ctx.user.role == Role.ADMINISTRATOR:
        from app.models.user import User
        rows = db.execute(select(User.email, func.count()).join(Investigation, Investigation.assigned_user_id == User.id).where(*openw).group_by(User.email).order_by(User.email)).all()
        sec.table("investigations_assignment", "investigations.assignment_distribution", "Open investigations per assignee (alphabetical; not a ranking or productivity measure)", ["assignee", "investigations"], [[e, int(c)] for e, c in rows])
    sec.sample_counts = {"visible_investigations": total_now, "created_in_window": nc, "closed_in_window": ncl}
    sec.freshness_from(db.scalar(select(func.max(Investigation.updated_at)).where(*vis)), "latest_investigation_update_at")
    sec.caveat("Only investigations you are allowed to open are counted; restricted investigations you cannot access are excluded entirely, so totals can differ between users.")
    sec.caveat("Counts and durations describe workflow volume, not the quality of analysis; they must not be used to rank analysts.")
    if total_now == 0:
        sec.status = "empty"
    sec.drilldown = {"investigations.by_status": "/investigations", "investigations.by_priority": "/investigations"}
    return sec.build()


# ----------------------------------------------------------------- evidence ---
def evidence_section(ctx: Ctx) -> dict:
    from app.models.investigation_workspace import EvidenceIntegrityCheck
    from app.models.investigation import Investigation
    from app.models.investigation_workspace import InvestigationNote
    from app.services.evidence_registry_service import RESTRICTED_READ_ROLES

    if not ctx.can(Permission.EVIDENCE_READ):
        return not_authorized("evidence", ctx, "evidence:read")
    sec = Section("evidence", ctx)
    db, w = ctx.db, ctx.window
    base = [Evidence.organization_id == ctx.org]
    if ctx.user.role not in RESTRICTED_READ_ROLES:
        base.append(Evidence.access_classification != "restricted")
        sec.caveat("Restricted evidence is excluded for your role.")
    where = base + [in_window(Evidence.created_at, w)]
    n = db.scalar(select(func.count()).select_from(Evidence).where(*where)) or 0
    sec.value("evidence.count", n, n)
    sec.table("evidence_by_type", "evidence.by_type", "Evidence by type (created in window)", ["evidence_type", "items"], _grouped(ctx, Evidence.evidence_type, where))
    sec.table("evidence_by_review_status", "evidence.by_review_status", "Evidence by review status (created in window)", ["review_status", "items"], _grouped(ctx, Evidence.review_status, where))
    no_origin = db.scalar(select(func.count()).select_from(Evidence).where(*where, Evidence.event_id.is_(None), Evidence.raw_record_id.is_(None), Evidence.observation_id.is_(None), Evidence.media_asset_id.is_(None),
                                                                           Evidence.detection_result_id.is_(None), Evidence.source_id.is_(None), Evidence.external_reference_uri.is_(None))) or 0
    sec.rate("evidence.missing_origin_rate", no_origin, n)
    no_hash = db.scalar(select(func.count()).select_from(Evidence).where(*where, Evidence.integrity_hash.is_(None))) or 0
    sec.rate("evidence.missing_integrity_hash_rate", no_hash, n)
    backlog = db.scalar(select(func.count()).select_from(Evidence).where(*base, Evidence.review_status.in_(("unreviewed", "in_review")))) or 0
    sec.value("evidence.review_backlog", backlog, backlog)
    cw = [EvidenceIntegrityCheck.organization_id == ctx.org, in_window(EvidenceIntegrityCheck.created_at, w),
          EvidenceIntegrityCheck.evidence_id.in_(select(Evidence.id).where(*base))]
    sec.table("evidence_integrity_checks", "evidence.integrity_checks_by_result", "Integrity checks by result (run in window)", ["result", "checks"], _grouped(ctx, EvidenceIntegrityCheck.result, cw))
    nw = [InvestigationNote.organization_id == ctx.org, in_window(InvestigationNote.created_at, w),
          InvestigationNote.investigation_id.in_(select(Investigation.id).where(*visible_investigation_clauses(ctx)))] if ctx.can(Permission.INVESTIGATION_READ) else None
    if nw is not None:
        sec.table("notes_by_kind", "evidence.notes_by_kind", "Analyst notes by kind (created in window)", ["note_kind", "notes"], _grouped(ctx, InvestigationNote.note_kind, nw))
    else:
        sec.caveat("Analyst-note counts omitted: they require investigation:read.")
    sec.sample_counts = {"evidence_items": n, "review_backlog": backlog}
    sec.freshness_from(db.scalar(select(func.max(Evidence.created_at)).where(*base)), "latest_evidence_created_at")
    sec.caveat("The number of evidence items says nothing about how strong the evidence is. A missing origin link or integrity hash is a documentation gap, not a finding about the item.")
    sec.caveat("An integrity hash is an integrity check of stored content only; it does not establish authenticity or provenance of the source.")
    if n == 0 and backlog == 0:
        sec.status = "empty"
    sec.drilldown = {"evidence.review_backlog": "/fusion/evidence", "evidence.by_type": "/fusion/evidence"}
    return sec.build()


# ------------------------------------------------------------------- models ---
def models_section(ctx: Ctx) -> dict:
    from app.models.inference_job import InferenceJob
    from app.models.mlops import ExperimentRun, ReviewSignal
    from app.models.model_record import ModelRecord
    from app.services import mlops_monitoring_service as mon
    from app.services import mlops_registry_service as reg

    if not ctx.can(Permission.MLOPS_READ):
        return not_authorized("models", ctx, "mlops:read")
    sec = Section("models", ctx)
    db, w = ctx.db, ctx.window
    vis = reg.visible_clause(ctx.org)
    models = db.execute(select(ModelRecord).where(vis).order_by(ModelRecord.name, ModelRecord.version, ModelRecord.id).limit(201)).scalars().all()
    capped = len(models) > 200
    models = models[:200]
    sec.table("versions_by_lifecycle", "models.versions_by_lifecycle", "Model versions by lifecycle state (current)", ["lifecycle_state", "versions"], _grouped(ctx, ModelRecord.lifecycle_state, [vis]))
    ev = reg.evaluation_status(db, ctx.org, [m.id for m in models])
    by_eval: dict[str, int] = {}
    for m in models:
        by_eval[ev[m.id]["status"]] = by_eval.get(ev[m.id]["status"], 0) + 1
    sec.table("evaluation_status", "models.evaluation_status", "Versions by derived evaluation status (current; 'passed' is not a quality claim)", ["status", "versions"], [[k, v] for k, v in sorted(by_eval.items())])
    rw = [ExperimentRun.organization_id == ctx.org, in_window(ExperimentRun.started_at, w)]
    sec.table("runs_by_status", "models.runs_by_status", "Experiment runs by status (start time)", ["status", "runs"], _grouped(ctx, ExperimentRun.status, rw))
    cap = get_settings().ANALYTICS_MAX_ROWS
    dur = sorted(d / 1000.0 for (d,) in db.execute(select(ExperimentRun.duration_ms).where(*rw, ExperimentRun.status.in_(("succeeded", "failed")), ExperimentRun.duration_ms.isnot(None)).limit(cap)).all())
    sec.value("models.run_duration_p50_seconds", percentile(dur, 0.5), len(dur), "no_finished_runs_in_window")
    # latest evaluations: stored values only
    run_ids = [ev[m.id]["latest_succeeded_run_id"] for m in models if ev[m.id]["latest_succeeded_run_id"]]
    runs = {r.id: r for r in db.execute(select(ExperimentRun).where(ExperimentRun.organization_id == ctx.org, ExperimentRun.id.in_(run_ids or [""]))).scalars()} if run_ids else {}
    rows = []
    for m in models[:100]:
        e = ev[m.id]
        r = runs.get(e["latest_succeeded_run_id"])
        metrics = {k: (round(v, 4) if isinstance(v, (int, float)) else v) for k, v in (e["metrics"] or {}).items()}
        rows.append([f"{m.name} {m.version}", m.task_type, e["status"], r.id if r else None, r.dataset_name if r else None, r.dataset_version if r else None,
                     r.sample_count if r else None, r.is_synthetic if r else None, ", ".join(f"{k}={v}" for k, v in sorted(metrics.items())) or None])
    sec.table("latest_evaluations", "models.latest_evaluations", "Latest succeeded evaluation per version (stored values; do not compare across different datasets)",
              ["model_version", "task", "evaluation_status", "run_id", "dataset", "dataset_version", "samples", "synthetic_data", "metrics"], rows)
    if capped or len(models) > 100:
        sec.caveat("Model tables are limited to the first 100/200 versions alphabetically.")
        sec.status = "partial"
    sg = db.execute(select(ReviewSignal.category, ReviewSignal.severity, func.count()).where(ReviewSignal.organization_id == ctx.org, ReviewSignal.status != "resolved")
                    .group_by(ReviewSignal.category, ReviewSignal.severity).order_by(ReviewSignal.category, ReviewSignal.severity)).all()
    sec.table("signals_by_category", "models.signals_by_category", "Open review signals by category and severity (current)", ["category", "severity", "signals"], [[a, b, int(c)] for a, b, c in sg])
    cov = mon.coverage_summary(db, ctx.org)
    sec.value("models.monitoring_coverage", cov["models_with_current_monitoring"], cov["models_total"])
    sec.table("monitoring_coverage", "models.monitoring_coverage", "Monitoring coverage per version (current)", ["model_version", "coverage", "age_days", "has_reference", "latest_samples"],
              [[f"{i['name']} {i['version']}", i["coverage"], i["age_days"], i["has_reference"], i["latest_sample_count"]] for i in cov["models"][:100]])
    jw = [InferenceJob.organization_id == ctx.org, in_window(InferenceJob.created_at, w)]
    by_job = dict(db.execute(select(InferenceJob.status, func.count()).where(*jw).group_by(InferenceJob.status)).all())
    sec.table("inference_jobs_by_status", "models.inference_jobs_by_status", "Inference jobs by status (created in window)", ["status", "jobs"], [[k, int(v)] for k, v in sorted(by_job.items())])
    fin = by_job.get("completed", 0) + by_job.get("failed", 0)
    sec.rate("models.inference_failure_rate", by_job.get("failed", 0), fin, get_settings().ANALYTICS_MIN_FINISHED_JOBS)
    ds = sorted((as_utc(f) - as_utc(s0)).total_seconds() for s0, f in db.execute(select(InferenceJob.started_at, InferenceJob.finished_at).where(*jw, InferenceJob.status == "completed", InferenceJob.started_at.isnot(None), InferenceJob.finished_at.isnot(None)).limit(cap)).all())
    sec.value("models.inference_duration_p50_seconds", percentile(ds, 0.5), len(ds), "no_completed_jobs_in_window")
    sec.value("models.inference_duration_p95_seconds", percentile(ds, 0.95), len(ds), "no_completed_jobs_in_window")
    sec.sample_counts = {"model_versions": len(models), "experiment_runs": sum(r[1] for r in sec.tables["runs_by_status"]["rows"]), "inference_jobs": sum(by_job.values())}
    sec.freshness_from(db.scalar(select(func.max(ExperimentRun.completed_at)).where(ExperimentRun.organization_id == ctx.org, ExperimentRun.status == "succeeded")), "latest_succeeded_run_at")
    sec.caveat("Evaluation metrics are the values stored when each run completed; this section never recomputes them. Metrics from different datasets, sample sizes or synthetic data are not comparable and are not ranked.")
    sec.caveat("Data drift and prediction drift describe a change in input/output distribution; performance degradation is a measured drop against labelled data. They are different signals and one does not imply the other.")
    if not models:
        sec.status = "empty"
    sec.drilldown = {"models.signals_by_category": "/mlops/review", "models.latest_evaluations": "/mlops/experiments", "models.monitoring_coverage": "/mlops/monitoring", "models.versions_by_lifecycle": "/mlops/models"}
    return sec.build()


# ------------------------------------------------------------------- system ---
def report_visibility_clauses(ctx: Ctx) -> list:
    from app.models.report import ReportRun

    c = [ReportRun.organization_id == ctx.org]
    if ctx.user.role != Role.ADMINISTRATOR:
        c.append(or_(ReportRun.visibility == "organization", ReportRun.created_by_user_id == ctx.user.id))
    return c


def system_section(ctx: Ctx) -> dict:
    from app.models.inference_job import InferenceJob
    from app.models.lifecycle import LifecycleRequest
    from app.models.report import ReportRun
    from app.services import health_service, observability_service

    if not ctx.can(Permission.REPORTING_READ):
        return not_authorized("system", ctx, "reporting:read")
    sec = Section("system", ctx)
    db, w = ctx.db, ctx.window
    checks = [("database", health_service.check_database(db)), ("model_runtime", health_service.check_model_runtime()), ("tracker_runtime", health_service.check_tracker_runtime()),
              ("sensor_analytics_runtime", health_service.check_sensor_analytics_runtime()), ("media_storage", health_service.check_media_storage())]
    sec.table("dependency_health", "system.dependency_health", f"Dependency readiness probes at {ctx.now.strftime('%Y-%m-%d %H:%MZ')} (point in time)", ["dependency", "status"], [[k, "ok" if ok else "failing"] for k, ok in checks])
    jobs: list[list] = []
    omitted = []
    if ctx.can(Permission.DATA_QUALITY_READ):
        jobs += [["ingestion", k, int(c)] for k, c in db.execute(select(IngestionJob.status, func.count()).where(IngestionJob.organization_id == ctx.org, in_window(IngestionJob.started_at, w)).group_by(IngestionJob.status).order_by(IngestionJob.status)).all()]
    else:
        omitted.append("ingestion")
    if ctx.can(Permission.FUSION_READ):
        jobs += [["fusion", k, int(c)] for k, c in db.execute(select(FusionJob.status, func.count()).where(FusionJob.organization_id == ctx.org, in_window(FusionJob.started_at, w)).group_by(FusionJob.status).order_by(FusionJob.status)).all()]
    else:
        omitted.append("fusion")
    if ctx.can(Permission.MLOPS_READ):
        jobs += [["inference", k, int(c)] for k, c in db.execute(select(InferenceJob.status, func.count()).where(InferenceJob.organization_id == ctx.org, in_window(InferenceJob.created_at, w)).group_by(InferenceJob.status).order_by(InferenceJob.status)).all()]
    else:
        omitted.append("inference")
    sec.table("jobs_by_status", "system.jobs_by_status", "Background job outcomes by kind and status (start time)", ["kind", "status", "jobs"], jobs)
    if omitted:
        sec.caveat(f"Job kinds omitted for lack of permission: {', '.join(omitted)}.")
        sec.status = "partial"
    if ctx.can(Permission.OBSERVABILITY_READ):
        m = observability_service.request_metrics_summary()
        sec.value("system.requests_total", int(m["requests_total"]), int(m["requests_total"]))
        sec.value("system.server_error_rate", m["server_error_rate"], int(m["requests_total"]), "no_requests_counted_since_process_start")
        lat = m["latency_seconds_upper_bound"]
        sec.value("system.latency_upper_bound_p50_seconds", lat["p50"], lat["observations"], "no_requests_counted_since_process_start")
        sec.value("system.latency_upper_bound_p95_seconds", lat["p95"], lat["observations"], "no_requests_counted_since_process_start")
        sec.caveat("API request metrics are per process, reset on restart and are not aggregated across workers; they are not windowed by the selected period.")
    else:
        sec.caveat("API request metrics omitted: they require observability:read.")
        sec.status = "partial"
    if ctx.can(Permission.LIFECYCLE_READ):
        sec.table("lifecycle_requests", "system.lifecycle_requests_by_status", "Data-lifecycle requests by status (created in window)", ["status", "requests"],
                  _grouped(ctx, LifecycleRequest.status, [LifecycleRequest.organization_id == ctx.org, in_window(LifecycleRequest.created_at, w)]))
    rw = report_visibility_clauses(ctx) + [in_window(ReportRun.created_at, w)]
    rows = db.execute(select(ReportRun.template_key, ReportRun.status, func.count()).where(*rw).group_by(ReportRun.template_key, ReportRun.status).order_by(ReportRun.template_key, ReportRun.status)).all()
    sec.table("reports_by_status", "system.reports_by_status", "Reports you can see, by template and status (created in window)", ["template", "status", "reports"], [[a, b, int(c)] for a, b, c in rows])
    sec.sample_counts = {"background_jobs": sum(r[2] for r in jobs), "reports": sum(int(r[2]) for r in rows)}
    sec.freshness = {"checked_at": ctx.now.isoformat(), "age_hours": 0.0, "stale": False, "note": "Dependency probes run at generation time."}
    sec.caveat("AEGIS does not collect uptime or queue-depth telemetry, so neither is shown. Dependency readiness is a point-in-time probe, not an availability percentage.")
    return sec.build()


# ---------------------------------------------------------------------- geo ---
GEO_RESOLUTION_DEG = 0.1


def geo_section(ctx: Ctx) -> dict:
    if not ctx.can(Permission.GEOSPATIAL_READ):
        return not_authorized("geo", ctx, "geospatial:read")
    sec = Section("geo", ctx)
    db, w, f, s = ctx.db, ctx.window, ctx.filters, get_settings()
    cap = s.ANALYTICS_MAX_ROWS
    res = GEO_RESOLUTION_DEG
    cells: dict[tuple[int, int], int] = {}
    unc: list[float] = []
    status_rows: list[list] = []
    n_valid = 0
    truncated = False
    for kind, model, type_col, perm in (("events", Event, Event.event_type, Permission.EVENT_READ), ("observations", Observation, Observation.observation_type, Permission.OBSERVATION_READ)):
        if not ctx.can(perm):
            sec.caveat(f"{kind.capitalize()} omitted: requires {perm.value}.")
            sec.status = "partial"
            continue
        where = [model.organization_id == ctx.org, in_window(_tcol(model, ctx), w)]
        if f.source_id:
            where.append(model.source_id == f.source_id)
        if f.category:
            where.append(type_col == f.category)
        if kind == "events" and not f.include_archived:
            where.append(Event.processing_status != "archived")
        total = db.scalar(select(func.count()).select_from(model).where(*where)) or 0
        no_loc = db.scalar(select(func.count()).select_from(model).where(*where, or_(model.latitude.is_(None), model.longitude.is_(None)))) or 0
        st = dict(db.execute(select(model.location_validation_status, func.count()).where(*where, model.latitude.isnot(None), model.longitude.isnot(None)).group_by(model.location_validation_status)).all())
        status_rows.append([kind, int(total), int(no_loc)] + [int(st.get(k, 0)) for k in ("valid", "invalid_range", "non_finite", "unsupported_crs")])
        rows = db.execute(select(model.latitude, model.longitude, model.location_uncertainty_m).where(*where, model.latitude.isnot(None), model.longitude.isnot(None), model.location_validation_status == "valid").limit(cap + 1)).all()
        if len(rows) > cap:
            truncated = True
        for la, lo, u in rows[:cap]:
            if not (math.isfinite(la) and math.isfinite(lo) and -90 <= la <= 90 and -180 <= lo <= 180):
                continue  # defence in depth: never bin a coordinate that fails validation
            n_valid += 1
            key = (math.floor(la / res), math.floor(lo / res))
            cells[key] = cells.get(key, 0) + 1
            if u is not None and math.isfinite(u):
                unc.append(float(u))
    sec.table("coordinate_status", "geo.coordinate_status", "Coordinate availability and validation in window", ["record_kind", "records", "no_coordinates", "valid", "invalid_range", "non_finite", "unsupported_crs"], status_rows)
    k = s.ANALYTICS_GEO_MIN_CELL_COUNT
    shown = sorted(((key, c) for key, c in cells.items() if c >= k), key=lambda kv: (-kv[1], kv[0]))[:200]
    suppressed_cells = sum(1 for c in cells.values() if c < k)
    suppressed_records = sum(c for c in cells.values() if c < k)
    sec.table("grid_cells", "geo.grid_cells", f"Records per {res}° grid cell (cells with fewer than {k} records suppressed)", ["cell_south_lat", "cell_west_lon", "cell_size_deg", "records"],
              [[round(key[0] * res, 4), round(key[1] * res, 4), res, c] for key, c in shown], "records")
    sec.value("geo.median_uncertainty_m", percentile(sorted(unc), 0.5), len(unc), "no_in_window_record_reports_location_uncertainty")
    sec.sample_counts = {"records_with_valid_coordinates": n_valid, "cells_shown": len(shown), "cells_suppressed": suppressed_cells, "records_in_suppressed_cells": suppressed_records}
    sec.freshness_from(db.scalar(select(func.max(Event.ingested_at)).where(Event.organization_id == ctx.org)), "latest_event_ingested_at")
    sec.caveat(f"Spatial precision is {res}° (about {round(res * 111)} km north-south); only cell-level counts are returned, never individual coordinates, and cells with fewer than {k} records are suppressed.")
    sec.caveat("Counts show where stored records are located, not where activity occurs. Records without valid coordinates are excluded from the grid. Location uncertainty is stated per record where reported and is not applied to the grid.")
    if truncated:
        sec.caveat("The grid uses only the most recent ANALYTICS_MAX_ROWS rows per record kind; it is partial.")
        sec.status = "partial"
    if n_valid == 0 and sec.status == "ok":
        sec.status = "empty"
    sec.drilldown = {"geo.coordinate_status": "/geospatial/quality", "geo.grid_cells": "/geospatial/map"}
    return sec.build()


# ----------------------------------------------------------- review backlog ---
def review_backlog_section(ctx: Ctx) -> dict:
    from app.models.investigation import Investigation
    from app.models.observation_anomaly import ObservationAnomaly
    from app.models.mlops import ReviewSignal
    from app.models.assessment import Assessment
    from app.services.evidence_registry_service import RESTRICTED_READ_ROLES

    sec = Section("review_backlog", ctx)
    db = ctx.db
    rows, omitted = [], []

    def cnt(model, *where):
        return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)

    if ctx.can(Permission.EVIDENCE_READ):
        ew = [Evidence.organization_id == ctx.org, Evidence.review_status.in_(("unreviewed", "in_review"))]
        if ctx.user.role not in RESTRICTED_READ_ROLES:
            ew.append(Evidence.access_classification != "restricted")
        rows.append(["evidence awaiting review", cnt(Evidence, *ew), "/fusion/evidence"])
    else:
        omitted.append("evidence")
    if ctx.can(Permission.FUSION_READ):
        rows.append(["correlation candidates", cnt(EventCorrelation, EventCorrelation.organization_id == ctx.org, EventCorrelation.review_status == "candidate"), "/correlation"])
        rows.append(["unresolved conflicts", cnt(Conflict, Conflict.organization_id == ctx.org, Conflict.review_status == "unresolved"), "/fusion/conflicts"])
        rows.append(["relationship candidates", cnt(EvidenceRelationship, EvidenceRelationship.organization_id == ctx.org, EvidenceRelationship.review_status == "candidate"), "/fusion/relationships"])
    else:
        omitted.append("fusion")
    if ctx.can(Permission.ANOMALY_READ):
        rows.append(["unreviewed anomalies", cnt(ObservationAnomaly, ObservationAnomaly.organization_id == ctx.org, ObservationAnomaly.review_status == "unreviewed"), "/sensors/anomalies"])
    else:
        omitted.append("anomalies")
    if ctx.can(Permission.INVESTIGATION_READ):
        rows.append(["investigations pending review", cnt(Investigation, *visible_investigation_clauses(ctx), Investigation.status == "pending_review"), "/investigations"])
    else:
        omitted.append("investigations")
    if ctx.can(Permission.ASSESSMENT_READ):
        rows.append(["assessments in review", cnt(Assessment, Assessment.organization_id == ctx.org, Assessment.status == "in_review"), "/fusion/assessments"])
    else:
        omitted.append("assessments")
    if ctx.can(Permission.MLOPS_READ):
        rows.append(["open model review signals", cnt(ReviewSignal, ReviewSignal.organization_id == ctx.org, ReviewSignal.status != "resolved"), "/mlops/review"])
    else:
        omitted.append("model signals")
    sec.table("review_backlog", "review.backlog", "Items awaiting human review (current)", ["queue", "items", "link"], rows)
    sec.value("review.backlog", sum(r[1] for r in rows), len(rows))
    sec.sample_counts = {"queues_shown": len(rows), "queues_omitted": len(omitted)}
    sec.freshness = {"checked_at": ctx.now.isoformat(), "age_hours": 0.0, "stale": False, "note": "Live counts at generation time."}
    if omitted:
        sec.caveat(f"Queues omitted for lack of permission: {', '.join(omitted)}.")
        sec.status = "partial"
    sec.caveat("These are current counts of items waiting for a person; the window does not apply. Their age and priority are not shown here.")
    if not rows:
        sec.status = "not_authorized"
    elif all(r[1] == 0 for r in rows) and sec.status == "ok":
        sec.status = "empty"
    return sec.build()


SECTIONS: dict[str, Callable[[Ctx], dict]] = {
    "events": events_section, "observations": observations_section, "ingestion": ingestion_section, "fusion": fusion_section, "sensors": sensors_section,
    "investigations": investigations_section, "evidence": evidence_section, "models": models_section, "system": system_section, "geo": geo_section,
    "review_backlog": review_backlog_section,
}


def build_section(ctx: Ctx, section_id: str) -> dict:
    return SECTIONS[section_id](ctx)


# ---------------------------------------------------------------- executive ---
HEADLINES = [
    ("events", "events.count"), ("observations", "observations.count"), ("ingestion", "ingestion.failure_rate"), ("ingestion", "ingestion.raw_invalid_rate"),
    ("observations", "observations.not_usable_rate"), ("sensors", "sensors.silent_count"), ("fusion", "fusion.conflicts_unresolved"), ("evidence", "evidence.review_backlog"),
    ("investigations", "investigations.created_count"), ("investigations", "investigations.closed_count"), ("review_backlog", "review.backlog"), ("models", "models.monitoring_coverage"),
]


def executive_dashboard(ctx: Ctx) -> dict:
    """Composes the same section functions the reports use, so a number on the dashboard
    and in a report share one definition. No composite or 'threat' score is produced."""
    order = ("events", "observations", "ingestion", "sensors", "fusion", "investigations", "evidence", "models", "review_backlog")
    sections = {sid: SECTIONS[sid](ctx) for sid in order}
    kpis = []
    for sid, mid in HEADLINES:
        sec = sections[sid]
        v = sec["values"].get(mid)
        meta = defs.CATALOG[mid]
        kpis.append({"metric_id": mid, "label": meta["label"], "section": sid, "unit": meta["unit"], "value": v["value"] if v else None, "n": v["n"] if v else None,
                     "reason": (v["reason"] if v else ("not_authorized" if sec["status"] == "not_authorized" else "unavailable")), "section_status": sec["status"],
                     "stale": (sec["freshness"] or {}).get("stale")})
    statuses = {sid: s["status"] for sid, s in sections.items()}
    return {"generated_at": ctx.now.isoformat(), "definition_version": defs.DEFINITION_VERSION, "window": ctx.window.describe(), "filters": ctx.filters.describe(),
            "kpis": kpis, "section_status": statuses, "sections": sections,
            "caveats": ["Figures are counts and rates over stored records; none is a threat score or a judgement about intent.",
                        "Sections you are not authorised to read are shown as not_authorized and contribute no numbers."]}
