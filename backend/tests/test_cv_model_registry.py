"""Phase 4, Section 4/17: the CV model registry -- extending the
Phase 1 `ModelRecord` table rather than a parallel `CVModel` table.
"""
from __future__ import annotations

import pytest

from app.cv.adapters.registry import UnsupportedRuntimeError, available_adapter_keys, get_adapter
from app.models.model_record import ModelRecord
from app.services import model_registry_service


def test_available_adapter_keys_lists_both_shipped_adapters():
    keys = available_adapter_keys()
    assert "mock_detector_v1" in keys
    assert "opencv_hog_person_v1" in keys


def test_unknown_adapter_key_raises_a_clean_documented_error():
    with pytest.raises(UnsupportedRuntimeError, match="not available"):
        get_adapter("ultralytics_yolo_v8_not_installed")


def test_register_cv_model_rejects_unknown_adapter_key(db):
    with pytest.raises(ValueError, match="not a registered adapter"):
        model_registry_service.register_cv_model(
            db, name="x", version="1", adapter_key="nonexistent_adapter", supported_media_types=["image"],
        )


def test_register_cv_model_rejects_unknown_media_type(db):
    with pytest.raises(ValueError, match="not a supported media type"):
        model_registry_service.register_cv_model(
            db, name="x", version="1", adapter_key="mock_detector_v1", supported_media_types=["audio"],
        )


def test_register_cv_model_is_idempotent_on_name_and_version(db):
    first = model_registry_service.register_cv_model(db, name="dup", version="1", adapter_key="mock_detector_v1", supported_media_types=["image"])
    second = model_registry_service.register_cv_model(db, name="dup", version="1", adapter_key="mock_detector_v1", supported_media_types=["image"])
    assert first.id == second.id


def test_pre_prompt4_model_record_is_not_a_cv_model(db, org):
    legacy = ModelRecord(name="legacy-risk-model", version="v0", model_type="heuristic", status="registered")
    db.add(legacy)
    db.commit()
    db.refresh(legacy)

    assert legacy.task_type is None
    assert model_registry_service.get_cv_model(db, legacy.id) is None
    cv_models = db.execute(model_registry_service.list_cv_models_query()).scalars().all()
    assert legacy.id not in [m.id for m in cv_models]


def test_cv_model_registered_is_listed_and_supports_check(db, cv_mock_model):
    cv_models = db.execute(model_registry_service.list_cv_models_query()).scalars().all()
    assert cv_mock_model.id in [m.id for m in cv_models]
    assert model_registry_service.model_supports_media_type(cv_mock_model, "image")
    assert model_registry_service.model_supports_media_type(cv_mock_model, "video")
    assert not model_registry_service.model_supports_media_type(cv_mock_model, "audio")


def test_cv_models_api_requires_permission(client, tokens, auth_header):
    response = client.get("/api/v1/cv/models", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200  # MODEL_READ is granted to every role

    response = client.post(
        "/api/v1/cv/models", headers=auth_header(tokens, "viewer"),
        json={"name": "x", "version": "1", "adapter_key": "mock_detector_v1", "supported_media_types": ["image"]},
    )
    assert response.status_code == 403  # MODEL_MANAGE is admin-only


def test_register_cv_model_via_api_as_admin(client, tokens, auth_header):
    response = client.post(
        "/api/v1/cv/models", headers=auth_header(tokens, "admin"),
        json={"name": "api-registered", "version": "1", "adapter_key": "mock_detector_v1", "supported_media_types": ["image", "video"]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["adapter_key"] == "mock_detector_v1"
    assert body["task_type"] == "object_detection"
