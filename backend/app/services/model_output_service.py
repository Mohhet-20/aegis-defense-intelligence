"""Normalizes existing stored model outputs (detection results, risk
assessments) into the shared `ModelOutput` schema.

Read-only: nothing is copied into a new table. Nothing is invented --
a missing confidence stays missing, a missing model version is reported
as a data-quality warning, and a row that fails schema validation is
skipped from lists (and counted) or reported as invalid on direct fetch.
"""
from __future__ import annotations

from typing import Optional

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.detection_result import DETECTION_SCHEMA_VERSION, DetectionResult
from app.models.evidence import Evidence
from app.models.inference_job import InferenceJob
from app.models.model_record import ModelRecord
from app.models.risk_assessment import RiskAssessment
from app.schemas.model_output import (
    OUTPUT_TYPES,
    DataQualityIndicator,
    ModelOutput,
    ModelRef,
    RecordRef,
)
from app.services.timeutil import ensure_utc

LOW_CONFIDENCE_THRESHOLD = 0.5
TINY_BOX_AREA_FRACTION = 0.005


class ModelOutputInvalid(ValueError):
    """A stored row exists but does not satisfy the shared schema."""


def _model_ref(model: Optional[ModelRecord], fallback_name: str) -> ModelRef:
    if model is None:
        return ModelRef(name=fallback_name, version="unversioned")
    return ModelRef(model_record_id=model.id, name=model.name, version=model.version or "unversioned",
                    adapter_key=model.adapter_key, evaluation_metadata=model.evaluation_metadata or {})


def _detection_output(db: Session, d: DetectionResult) -> ModelOutput:
    model = db.get(ModelRecord, d.model_record_id)
    job = db.get(InferenceJob, d.inference_job_id)
    area = (d.bbox_x_max - d.bbox_x_min) * (d.bbox_y_max - d.bbox_y_min)
    dq: list[DataQualityIndicator] = []
    if d.confidence < LOW_CONFIDENCE_THRESHOLD:
        dq.append(DataQualityIndicator(code="low_confidence", severity="warning", message=f"Reported confidence {d.confidence:.2f} is below {LOW_CONFIDENCE_THRESHOLD}."))
    if area < TINY_BOX_AREA_FRACTION:
        dq.append(DataQualityIndicator(code="tiny_bounding_box", severity="warning", message="Bounding box covers under 0.5% of the frame; small detections are usually less reliable."))
    if d.class_label == "mock_object" or (model is not None and (model.adapter_key or "").startswith("mock")):
        dq.append(DataQualityIndicator(code="mock_model_output", severity="warning", message="Produced by a deterministic mock adapter, not a real detector."))
    if d.review_status == "unreviewed":
        dq.append(DataQualityIndicator(code="unreviewed", severity="info", message="No analyst has reviewed this detection."))
    if d.schema_version != DETECTION_SCHEMA_VERSION:
        dq.append(DataQualityIndicator(code="schema_version_mismatch", severity="warning", message=f"Stored under detection schema {d.schema_version}; current is {DETECTION_SCHEMA_VERSION}."))
    if job is not None and job.status != "completed":
        dq.append(DataQualityIndicator(code="job_not_completed", severity="error", message=f"Producing inference job status is '{job.status}'."))
    if model is None:
        dq.append(DataQualityIndicator(code="model_record_missing", severity="error", message="The model registry row is missing."))

    evidence_ids = db.execute(select(Evidence.id).where(Evidence.detection_result_id == d.id, Evidence.organization_id == d.organization_id)).scalars().all()
    supporting = [RecordRef(type="evidence", id=i) for i in evidence_ids]
    supporting.append(RecordRef(type="inference_job", id=d.inference_job_id))
    supporting.append(RecordRef(type="media_asset", id=d.media_asset_id))
    return ModelOutput(
        output_type="detection_result", output_id=d.id, organization_id=d.organization_id,
        model=_model_ref(model, "unknown model"),
        input_refs=[RecordRef(type="media_asset", id=d.media_asset_id)],
        source_refs=[RecordRef(type="inference_job", id=d.inference_job_id)],
        prediction={"kind": "object_detection", "label": d.class_label},
        confidence=d.confidence, confidence_provided=True,
        confidence_note="The detector's own score for this box; not a calibrated probability unless the model documents calibration.",
        processed_at=ensure_utc(d.created_at),
        execution_status={"completed": "completed", "failed": "failed"}.get(job.status if job else "", "unknown"),
        data_quality=dq,
        features={"bbox": {"x_min": d.bbox_x_min, "y_min": d.bbox_y_min, "x_max": d.bbox_x_max, "y_max": d.bbox_y_max},
                  "frame_index": d.frame_index, "frame_timestamp_seconds": d.frame_timestamp_seconds},
        explanation_metadata={"schema_version": d.schema_version, "raw_model_output_keys": sorted((d.raw_model_output or {}).keys())},
        supporting_records=supporting, review_status=d.review_status,
    )


def _risk_output(db: Session, r: RiskAssessment) -> ModelOutput:
    model = db.get(ModelRecord, r.model_record_id) if r.model_record_id else None
    dq: list[DataQualityIndicator] = []
    if model is None:
        dq.append(DataQualityIndicator(code="no_model_version", severity="warning", message=f"Produced by method '{r.method}' with no registered model version."))
    if r.confidence is None:
        dq.append(DataQualityIndicator(code="confidence_not_provided", severity="info", message="The method did not provide a confidence; none has been estimated."))
    if r.data_origin == "synthetic_demo":
        dq.append(DataQualityIndicator(code="synthetic_demo_data", severity="warning", message="Seeded synthetic demonstration data, not a real assessment."))
    if r.method.startswith("seed_example"):
        dq.append(DataQualityIndicator(code="seed_example_method", severity="warning", message="Produced by a seed example method; no real scoring model ran."))
    if not r.evidence_refs:
        dq.append(DataQualityIndicator(code="no_evidence_refs", severity="warning", message="No evidence references are recorded for this score."))
    if not r.contributing_factors:
        dq.append(DataQualityIndicator(code="no_contributing_factors", severity="info", message="No contributing factors are recorded, so no rule-based explanation is available."))
    refs = [RecordRef(type=str(e.get("type", "reference")), id=str(e.get("id", ""))) if isinstance(e, dict) else RecordRef(type="reference", id=str(e)) for e in (r.evidence_refs or [])]
    return ModelOutput(
        output_type="risk_assessment", output_id=r.id, organization_id=r.organization_id,
        model=_model_ref(model, r.method),
        input_refs=[RecordRef(type=r.subject_type, id=r.subject_id)], source_refs=[],
        prediction={"kind": "risk_score", "value": r.score, "scale": r.score_scale, "method": r.method},
        confidence=r.confidence, confidence_provided=r.confidence is not None,
        confidence_note=None if r.confidence is not None else "Not provided by the method.",
        processed_at=ensure_utc(r.assessed_at), execution_status="completed", data_quality=dq,
        features={"contributing_factors": r.contributing_factors or [], "stored_explanation": r.explanation},
        explanation_metadata={"data_origin": r.data_origin},
        supporting_records=refs, review_status=r.human_review_status,
    )


def to_model_output(db: Session, obj) -> ModelOutput:
    try:
        if isinstance(obj, DetectionResult):
            return _detection_output(db, obj)
        return _risk_output(db, obj)
    except ValidationError as exc:
        raise ModelOutputInvalid(f"stored record {obj.id} does not satisfy the model-output schema: {exc.errors()[0]['msg']}") from exc


def _query(output_type: str, organization_id: str, model_record_id: Optional[str]):
    if output_type not in OUTPUT_TYPES:
        raise ValueError(f"output_type must be one of {OUTPUT_TYPES}")
    if output_type == "detection_result":
        stmt = select(DetectionResult).where(DetectionResult.organization_id == organization_id)
        if model_record_id:
            stmt = stmt.where(DetectionResult.model_record_id == model_record_id)
        return stmt.order_by(DetectionResult.created_at.desc(), DetectionResult.id)
    stmt = select(RiskAssessment).where(RiskAssessment.organization_id == organization_id)
    if model_record_id:
        stmt = stmt.where(RiskAssessment.model_record_id == model_record_id)
    return stmt.order_by(RiskAssessment.assessed_at.desc(), RiskAssessment.id)


def get_output(db: Session, organization_id: str, output_type: str, output_id: str) -> Optional[ModelOutput]:
    model_cls = DetectionResult if output_type == "detection_result" else RiskAssessment
    if output_type not in OUTPUT_TYPES:
        raise ValueError(f"output_type must be one of {OUTPUT_TYPES}")
    obj = db.execute(select(model_cls).where(model_cls.id == output_id, model_cls.organization_id == organization_id)).scalar_one_or_none()
    return None if obj is None else to_model_output(db, obj)


def list_outputs(db: Session, organization_id: str, output_type: str, *, model_record_id: Optional[str], page: int, page_size: int) -> dict:
    stmt = _query(output_type, organization_id, model_record_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).scalars().all()
    items, skipped = [], 0
    for row in rows:
        try:
            items.append(to_model_output(db, row))
        except ModelOutputInvalid:
            skipped += 1
    return {"items": items, "total": total, "page": page, "page_size": page_size, "skipped_invalid": skipped}
