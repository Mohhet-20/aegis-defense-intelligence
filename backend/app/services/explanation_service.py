"""Builds an explanation for one stored model output (Section 4). Computed on demand and deterministic -- nothing is
persisted, so an explanation can never drift from the output it
describes."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.analytics import explainers
from app.services import model_output_service


class UnknownExplanationMethod(ValueError):
    pass


def explain_output(db: Session, organization_id: str, output_type: str, output_id: str, method_key: Optional[str]) -> Optional[dict]:
    output = model_output_service.get_output(db, organization_id, output_type, output_id)
    if output is None:
        return None
    payload = output.model_dump(mode="python")
    try:
        result = explainers.explain(payload, method_key)
    except KeyError:
        raise UnknownExplanationMethod(f"unknown explanation method '{method_key}' (available: {sorted(explainers.EXPLAINERS)})")
    result["output_type"] = output_type
    result["output_id"] = output_id
    result["data_quality"] = [i.model_dump() for i in output.data_quality]
    return result
