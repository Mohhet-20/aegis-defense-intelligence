from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class SubmitTrackingJobRequest(BaseModel):
    inference_job_id: str
    tracker_key: Optional[str] = None
    min_iou_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    # Deliberately no upper bound on max_missed_frames/min_hits_to_confirm
    # here -- same "clamp server-side, never reject the request" lesson
    # Already learned; there is no settings-level clamp needed for these two
    # because they are per-job configuration choices, not a resource
    # bound, but ge=0/ge=1 still rejects nonsensical negative input.
    max_missed_frames: Optional[int] = Field(default=None, ge=0)
    min_hits_to_confirm: Optional[int] = Field(default=None, ge=1)
    require_class_match: Optional[bool] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=128)


class TrackingJobResponse(BaseModel):
    id: str
    organization_id: str
    media_asset_id: str
    inference_job_id: str
    tracker_key: str
    tracker_version: str
    status: str
    result_schema_version: str
    config: dict
    frames_considered: int
    frames_processed: int
    detections_considered: int
    tracks_created: int
    idempotency_key: Optional[str]
    retry_count: int
    retried_from_job_id: Optional[str]
    triggered_by_user_id: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    error_category: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[misc]
    @property
    def processing_duration_seconds(self) -> Optional[float]:
        """Always DERIVED from started_at/finished_at, never its own
        stored column -- it can never drift from the two timestamps
        that actually define it. None until the job has both started
        and finished (Section 3A: "Processing duration, when measured")."""
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()


class TrackResponse(BaseModel):
    id: str
    organization_id: str
    tracking_job_id: str
    sequence_track_id: str
    class_label: Optional[str]
    first_frame_index: int
    last_frame_index: int
    first_timestamp_seconds: float
    last_timestamp_seconds: float
    matched_observations_count: int
    missed_frames_count: int
    state: str
    quality_summary: dict
    lifecycle_events: list
    created_at: datetime

    model_config = {"from_attributes": True}


class TrackObservationResponse(BaseModel):
    id: str
    track_id: str
    detection_result_id: str
    media_asset_id: str
    frame_index: int
    frame_timestamp_seconds: float
    bbox_x_min: float
    bbox_y_min: float
    bbox_x_max: float
    bbox_y_max: float
    class_label: str
    confidence: float
    association_method: str
    association_cost: Optional[float]
    observation_state: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TrackingJobSummaryResponse(BaseModel):
    tracks_by_state: dict
    total_tracks: int
    mean_track_duration_seconds: float
    total_observations: int


class TrackMotionStepResponse(BaseModel):
    from_frame_index: int
    to_frame_index: int
    elapsed_seconds: float
    center_from_px: list[float]
    center_to_px: list[float]
    displacement_px: float
    direction_degrees: Optional[float]


class TrackMotionResponse(BaseModel):
    unit_note: str
    observation_count: int
    duration_seconds: float
    total_path_length_px: float
    net_displacement_px: float
    bbox_area_px_first: float
    bbox_area_px_last: float
    bbox_area_change_ratio: Optional[float]
    missed_sampled_frame_count: int
    missing_frame_indices: list[int]
    fragmentation_count: int
    steps: list[TrackMotionStepResponse]


class TrackerConfigOption(BaseModel):
    tracker_key: str
    tracker_version: str
    is_deterministic: bool


class TrackerConfigDefaultsResponse(BaseModel):
    available_trackers: list[TrackerConfigOption]
    default_tracker_key: str
    min_iou_threshold: float
    max_missed_frames: int
    min_hits_to_confirm: int
    require_class_match: bool
    max_active_tracks_per_job: int
