from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field, field_validator

T = TypeVar("T")


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class ErrorResponse(BaseModel):
    detail: str
    request_id: Optional[str] = None


class GeoLocationFields(BaseModel):
    """Mixin for request/response schemas carrying optional coordinates.
    Section 7: validate range when present; never invent a
    value when absent. Extended (Section 3) with
    the provenance/uncertainty fields app/models/mixins.py's
    GeoLocationMixin now carries -- every table that already composed
    this schema mixin (Event/Asset/Sensor/Observation) picks these up
    automatically, no per-schema edits needed."""

    latitude: Optional[float] = None
    longitude: Optional[float] = None
    coordinate_reference_system: str = "WGS84"
    location_origin: Optional[str] = None
    location_validation_status: Optional[str] = None
    location_uncertainty_m: Optional[float] = None
    altitude_m: Optional[float] = None
    altitude_reference: Optional[str] = None
    location_provenance_note: Optional[str] = None

    @field_validator("latitude")
    @classmethod
    def _validate_latitude(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-90.0 <= v <= 90.0):
            raise ValueError("latitude must be between -90 and 90")
        return v

    @field_validator("longitude")
    @classmethod
    def _validate_longitude(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-180.0 <= v <= 180.0):
            raise ValueError("longitude must be between -180 and 180")
        return v


class GeoLocationResponseFields(GeoLocationFields):
    """Response variant: returns stored coordinates as they are. Requests are
    range-validated (GeoLocationFields), but a legacy or directly written row with an
    out-of-range value must not turn a whole list into a 500; such values are
    classified by the location-quality checks (app/geo/validation.py) instead."""

    @field_validator("latitude")
    @classmethod
    def _validate_latitude(cls, v: Optional[float]) -> Optional[float]:
        return v

    @field_validator("longitude")
    @classmethod
    def _validate_longitude(cls, v: Optional[float]) -> Optional[float]:
        return v
