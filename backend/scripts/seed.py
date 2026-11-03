"""Deterministic seed-data command. Every record created
here that stands in for real-world data is explicitly labeled
data_origin="synthetic_demo" (Rule 9) -- this script never claims to
have connected to a real external system. Run from backend/:

    python scripts/seed.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.demo import DEMO_PASSWORD
from app.core.security import hash_password
from app.db.session import SessionLocal, engine
import app.models  # noqa: F401
from app.models.asset import Asset
from app.models.data_source import DataSource
from app.models.event import Event
from app.models.ingestion_job import IngestionJob
from app.models.investigation import Investigation
from app.models.model_record import ModelRecord
from app.models.observation import Observation
from app.models.organization import Organization
from app.models.risk_assessment import RiskAssessment
from app.models.sensor import Sensor
from app.models.user import User
from app.services import anomaly_service, sensor_ingestion_service, spatial_relationship_service

DEV_PASSWORD = DEMO_PASSWORD  # one documented password, defined in app/core/demo.py


def _require_migrated_schema() -> None:
    """Seed only a database that `alembic upgrade head` has brought fully up to date.

    This script used to call Base.metadata.create_all(), which on a database that
    was behind (or empty) created tables outside Alembic's knowledge, so the next
    `alembic upgrade head` failed with "table already exists".
    """
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    heads = set(ScriptDirectory.from_config(cfg).get_heads())
    with engine.connect() as conn:
        current = set(MigrationContext.configure(conn).get_current_heads())
    if current != heads:
        raise SystemExit(
            f"Refusing to seed: database revision {sorted(current) or 'none'} is not the migration head "
            f"{sorted(heads)}. Run `alembic upgrade head` in backend/ first."
        )


def main() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    if settings.ENVIRONMENT.lower() == "production" and not settings.DEMO_MODE:
        # The seeded accounts share a publicly documented password.
        raise SystemExit("Refusing to seed: ENVIRONMENT=production. The demo accounts use a documented password "
                         "(allowed only for a public showcase with DEMO_MODE=true).")
    _require_migrated_schema()
    db = SessionLocal()
    try:
        org = db.query(Organization).filter_by(name="AEGIS Demo Organization").first()
        if org is None:
            org = Organization(name="AEGIS Demo Organization", status="active")
            db.add(org)
            db.flush()

        existing_admin = db.query(User).filter_by(username="admin").first()
        if existing_admin is None:
            admin = User(
                organization_id=org.id, username="admin", email="admin@aegis-demo.example.com",
                display_name="Demo Administrator", password_hash=hash_password(DEV_PASSWORD),
                role="administrator", is_active=True,
            )
            analyst = User(
                organization_id=org.id, username="analyst", email="analyst@aegis-demo.example.com",
                display_name="Demo Analyst", password_hash=hash_password(DEV_PASSWORD),
                role="analyst", is_active=True,
            )
            investigator = User(
                organization_id=org.id, username="investigator", email="investigator@aegis-demo.example.com",
                display_name="Demo Investigator", password_hash=hash_password(DEV_PASSWORD),
                role="investigator", is_active=True,
            )
            viewer = User(
                organization_id=org.id, username="viewer", email="viewer@aegis-demo.example.com",
                display_name="Demo Viewer", password_hash=hash_password(DEV_PASSWORD),
                role="viewer", is_active=True,
            )
            db.add_all([admin, analyst, investigator, viewer])
            db.flush()
            print("Created demo accounts (development, or a DEMO_MODE showcase):")
            print(f"  admin         / {DEV_PASSWORD}")
            print(f"  analyst       / {DEV_PASSWORD}")
            print(f"  investigator  / {DEV_PASSWORD}")
            print(f"  viewer        / {DEV_PASSWORD}")
        else:
            admin = existing_admin

        source = db.query(DataSource).filter_by(name="Synthetic Demo Feed", organization_id=org.id).first()
        if source is None:
            source = DataSource(
                organization_id=org.id, name="Synthetic Demo Feed", source_type="synthetic_generator",
                description="Deterministic synthetic demonstration data -- not a real connected feed.",
                status="active", reliability_weight=1.0, config_metadata={"generator": "scripts/seed.py"},
            )
            db.add(source)
            db.flush()

        now = datetime.now(timezone.utc)

        if db.query(Asset).filter_by(organization_id=org.id).count() == 0:
            assets = [
                Asset(organization_id=org.id, name="North Gate Checkpoint", entity_type="facility", status="active", latitude=38.8977, longitude=-77.0365),
                Asset(organization_id=org.id, name="Patrol Vehicle 7", entity_type="vehicle", status="active", latitude=38.9, longitude=-77.03),
                Asset(organization_id=org.id, name="Perimeter Sensor Mast A", entity_type="equipment", status="active"),
            ]
            db.add_all(assets)
            db.flush()
        else:
            assets = db.query(Asset).filter_by(organization_id=org.id).all()

        if db.query(Sensor).filter_by(organization_id=org.id).count() == 0:
            sensors = [
                Sensor(organization_id=org.id, source_id=source.id, name="Gate Camera 1", sensor_type="camera", status="active", last_seen_at=now, latitude=38.8977, longitude=-77.0365),
                Sensor(organization_id=org.id, source_id=source.id, name="Perimeter GPS Beacon", sensor_type="gps", status="active", last_seen_at=now - timedelta(minutes=5)),
                Sensor(organization_id=org.id, source_id=source.id, name="Environmental Sensor 1", sensor_type="environmental", status="unknown"),
            ]
            db.add_all(sensors)
            db.flush()
        else:
            sensors = db.query(Sensor).filter_by(organization_id=org.id).all()

        if db.query(Event).filter_by(organization_id=org.id).count() == 0:
            event_rows = [
                Event(
                    organization_id=org.id, source_id=source.id, external_id=f"seed-event-{i}",
                    event_type=etype, title=title, description=desc,
                    observed_at=now - timedelta(hours=i), ingested_at=now - timedelta(hours=i) + timedelta(seconds=30),
                    latitude=lat, longitude=lon, asset_id=assets[0].id if lat else None,
                    source_severity=sev, priority=pri, confidence=conf,
                    attributes={"demo_index": i}, classification="unclassified",
                    provenance={"generator": "scripts/seed.py", "note": "synthetic demonstration record"},
                    processing_status="ingested", data_origin="synthetic_demo",
                )
                for i, (etype, title, desc, lat, lon, sev, pri, conf) in enumerate([
                    ("perimeter_motion", "Motion detected near North Gate", "Synthetic demo event.", 38.8977, -77.0365, "medium", "normal", 0.62),
                    ("unidentified_vehicle", "Unregistered vehicle approach", "Synthetic demo event.", 38.90, -77.031, "high", "high", 0.71),
                    ("sensor_offline", "Environmental Sensor 1 stopped reporting", "Synthetic demo event.", None, None, "low", "low", None),
                    ("access_attempt", "Badge access attempt outside hours", "Synthetic demo event.", 38.8977, -77.0365, "medium", "normal", 0.55),
                    ("anomalous_pattern", "Repeated loitering pattern observed", "Synthetic demo event.", 38.899, -77.032, "high", "urgent", 0.80),
                ])
            ]
            db.add_all(event_rows)
            db.flush()
        else:
            event_rows = db.query(Event).filter_by(organization_id=org.id).all()

        if db.query(Observation).filter_by(organization_id=org.id).count() == 0:
            observations = [
                Observation(
                    organization_id=org.id, sensor_id=sensors[0].id, source_id=source.id,
                    observed_at=now - timedelta(minutes=i * 10), observation_type="detection_summary",
                    payload={"object_count": i + 1, "demo": True}, provenance={"generator": "scripts/seed.py"},
                    data_origin="synthetic_demo", latitude=38.8977, longitude=-77.0365,
                )
                for i in range(3)
            ]
            db.add_all(observations)
            db.flush()

        # Phase 6: give the environmental sensor real registry metadata
        # (category/measurement_types/units/operating_range) -- nullable
        # fields an analyst would configure, never guessed for a sensor
        # that didn't have them before Phase 6 existed.
        env_sensor = sensors[2]
        if not env_sensor.measurement_types:
            env_sensor.category = "environmental"
            env_sensor.measurement_types = ["temperature_c"]
            env_sensor.measurement_units = {"temperature_c": "celsius"}
            env_sensor.operating_range = {"temperature_c": {"min": -10.0, "max": 45.0}}
            env_sensor.nominal_sampling_interval_seconds = 60.0
            env_sensor.expected_data_format = "json"
            db.add(env_sensor)
            db.flush()

        # Phase 6: run one deterministic synthetic batch through the
        # REAL ingestion pipeline (app/services/sensor_ingestion_service.py)
        # -- not hand-inserted rows -- so the seeded demo data exercises
        # the same quality/validation code path a live batch would. A
        # fixed seed makes this byte-identical on every run; a single
        # value_override deliberately produces one out-of-range reading
        # so the anomaly engine has something real (not fabricated) to
        # detect. Guarded by job_type so re-running seed.py is idempotent.
        existing_synthetic_job = (
            db.query(IngestionJob)
            .filter_by(organization_id=org.id, job_type="sensor_synthetic")
            .first()
        )
        if existing_synthetic_job is None:
            synthetic_job = sensor_ingestion_service.submit_synthetic_batch(
                db,
                organization_id=org.id,
                source_id=source.id,
                config={
                    "sensor_id": env_sensor.id,
                    "measurement_type": "temperature_c",
                    "unit": "celsius",
                    "count": 20,
                    "seed": 42,
                    "base_value": 22.0,
                    "noise_amplitude": 1.2,
                    "interval_seconds": 60.0,
                    "start_at": (now - timedelta(minutes=20)).isoformat(),
                    # Index 19 (the most recent reading) deliberately set
                    # well outside the configured operating_range above,
                    # so the seeded anomaly below is a genuine detection
                    # against a real synthetic series, not a staged row.
                    "value_overrides": {"19": 61.0},
                },
                created_by_user_id=admin.id,
                trigger_type="manual",
            )
            print(f"Seeded synthetic sensor batch: job={synthetic_job.id} accepted={synthetic_job.accepted_count} rejected={synthetic_job.rejected_count}")

            db.refresh(env_sensor)
            anomaly_result = anomaly_service.run_checks(
                db, organization_id=org.id, sensor=env_sensor, measurement_type="temperature_c",
            )
            print(f"Seeded anomaly check: created={len(anomaly_result['created'])} already_known={len(anomaly_result['already_known'])}")

        model_record = db.query(ModelRecord).filter_by(name="demo-risk-scorer").first()
        if model_record is None:
            model_record = ModelRecord(
                name="demo-risk-scorer", version="v0", model_type="heuristic",
                artifact_reference=None, status="registered",
                evaluation_metadata={"note": "placeholder registry row -- no real model backs this yet, see docs/architecture/AI_ANALYTICS_CONTRACTS.md"},
            )
            db.add(model_record)
            db.flush()

        # Phase 4: two real, runnable CV model registry rows -- the
        # deterministic mock adapter (works in any environment) and the
        # real OpenCV HOG person detector (works wherever
        # opencv-python-headless does, which is this environment). Both
        # extend this SAME `model_records` table; demo-risk-scorer above
        # is untouched (task_type stays NULL for it).
        if db.query(ModelRecord).filter_by(name="mock-object-detector").first() is None:
            db.add(ModelRecord(
                name="mock-object-detector", version="v1", model_type="computer_vision",
                task_type="object_detection", adapter_key="mock_detector_v1",
                supported_media_types=["image", "video"], status="active",
                evaluation_metadata={"note": "deterministic, non-ML mock adapter -- see docs/ml/MODEL_ADAPTERS.md"},
            ))
        if db.query(ModelRecord).filter_by(name="opencv-hog-person-detector").first() is None:
            db.add(ModelRecord(
                name="opencv-hog-person-detector", version="v1", model_type="computer_vision",
                task_type="object_detection", adapter_key="opencv_hog_person_v1",
                supported_media_types=["image", "video"], status="active",
                evaluation_metadata={"note": "real classical CV model (HOG+SVM), bundled with opencv-python-headless -- see docs/ml/MODEL_ADAPTERS.md"},
            ))
        if db.query(ModelRecord).filter_by(name="ssd-mobilenet-v1-coco").first() is None:
            db.add(ModelRecord(
                name="ssd-mobilenet-v1-coco", version="2017.11.17", model_type="computer_vision",
                task_type="object_detection", adapter_key="ssd_mobilenet_v1_coco",
                supported_media_types=["image", "video"], status="active",
                evaluation_metadata={"note": "pretrained deep detector (SSD + MobileNet v1, COCO; Apache-2.0). Weights are downloaded and "
                                             "SHA-256-verified by scripts/fetch_models.py; jobs fail with instructions until then. "
                                             "Classes: person, vehicle. See docs/ml/MODEL_ADAPTERS.md."},
            ))
        db.flush()

        if db.query(RiskAssessment).filter_by(organization_id=org.id).count() == 0:
            assessments = [
                RiskAssessment(
                    organization_id=org.id, subject_type="event", subject_id=event_rows[1].id,
                    assessed_at=now, method="seed_example_v0", model_record_id=model_record.id,
                    score=71.0, confidence=0.4,
                    contributing_factors=[{"factor": "unregistered_vehicle", "weight": 0.6}, {"factor": "after_hours", "weight": 0.4}],
                    evidence_refs=[event_rows[1].id],
                    explanation="Example explanation for demonstration purposes only -- not produced by a real scoring model. See docs/architecture/AI_ANALYTICS_CONTRACTS.md.",
                    human_review_status="pending", data_origin="synthetic_demo",
                ),
                RiskAssessment(
                    organization_id=org.id, subject_type="event", subject_id=event_rows[4].id,
                    assessed_at=now, method="seed_example_v0", model_record_id=model_record.id,
                    score=85.0, confidence=0.35,
                    contributing_factors=[{"factor": "repeated_loitering", "weight": 0.8}],
                    evidence_refs=[event_rows[4].id],
                    explanation="Example explanation for demonstration purposes only -- not produced by a real scoring model.",
                    human_review_status="pending", data_origin="synthetic_demo",
                ),
            ]
            db.add_all(assessments)
            db.flush()

        # Phase 7 (geospatial intelligence): a handful of additional
        # synthetic Event rows specifically chosen to exercise the
        # Geospatial Intelligence Workspace's own tabs -- a pair close
        # enough in space+time to produce a real "spatially_associated"
        # candidate below, plus one unsupported-CRS row and one
        # missing-coordinates row so the Location Quality Center has
        # real (not fabricated) findings to show on a fresh install.
        # Guarded by external_id prefix so re-running seed.py is
        # idempotent, same pattern as every other block in this file.
        if db.query(Event).filter_by(organization_id=org.id, external_id="seed-geo-event-0").first() is None:
            geo_event_rows = [
                Event(
                    organization_id=org.id, source_id=source.id, external_id=f"seed-geo-event-{i}",
                    event_type=etype, title=title, description="Synthetic demo event (Phase 7 geospatial seed).",
                    observed_at=now - timedelta(minutes=offset_min), ingested_at=now - timedelta(minutes=offset_min) + timedelta(seconds=15),
                    latitude=lat, longitude=lon, coordinate_reference_system=crs,
                    source_severity="low", priority="normal", confidence=0.5,
                    attributes={"demo_index": i}, classification="unclassified",
                    provenance={"generator": "scripts/seed.py", "note": "synthetic demonstration record -- Phase 7 geospatial seed"},
                    processing_status="ingested", data_origin="synthetic_demo",
                )
                for i, (etype, title, lat, lon, crs, offset_min) in enumerate([
                    # This pair is within the default spatial (500m) and
                    # temporal (30min) thresholds -- generate_candidates()
                    # below will link them.
                    ("perimeter_motion", "Motion near East Fence (A)", 38.9010, -77.0300, "WGS84", 30),
                    ("perimeter_motion", "Motion near East Fence (B)", 38.9011, -77.0301, "WGS84", 32),
                    # Too far from anything else to be spatially associated --
                    # demonstrates a "no candidates" case is possible too.
                    ("unidentified_vehicle", "Unregistered vehicle, south perimeter", 38.85, -77.10, "WGS84", 45),
                    # A coordinate reference system this project does not
                    # support -- app/geo/validation.py flags this as
                    # "unsupported_crs", never silently treated as WGS84.
                    # The numeric values are deliberately plausible
                    # latitude/longitude-shaped numbers (not real UTM
                    # easting/northing, which would be in the hundreds of
                    # thousands and would instead trip the EARLIER
                    # invalid_range check -- see validate_coordinates's
                    # checked order in app/geo/validation.py): this row
                    # exists specifically to demonstrate the
                    # unsupported_crs finding, not an invalid_range one.
                    ("sensor_offline", "Legacy feed reporting in local grid coordinates", 38.90, -77.03, "UTM18N", 50),
                    # Coordinates genuinely absent (not zero) -- a real,
                    # common case: this report never included a location.
                    ("access_attempt", "Badge access attempt, location not reported by source", None, None, "WGS84", 55),
                ])
            ]
            db.add_all(geo_event_rows)
            db.commit()
            print(f"Seeded {len(geo_event_rows)} geospatial demo events.")

            relationship_result = spatial_relationship_service.generate_candidates(db, org.id)
            print(
                f"Seeded spatial-relationship candidates: created={relationship_result.candidates_created} "
                f"already_known={relationship_result.candidates_already_known} pairs_considered={relationship_result.pairs_considered}"
            )

        if db.query(Investigation).filter_by(organization_id=org.id).count() == 0:
            investigation = Investigation(
                organization_id=org.id, title="Repeated loitering near North Gate",
                description="Synthetic demo investigation linking the loitering and vehicle events.",
                status="open", priority="high", assigned_user_id=admin.id,
                linked_event_ids=[event_rows[1].id, event_rows[4].id], evidence_refs=[],
                review_status="not_reviewed",
            )
            db.add(investigation)
            db.flush()

        db.commit()
        print("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
