// Mirrors backend/app/schemas/*.py exactly -- every field here is a
// real response field, never an invented convenience field. If the
// backend schema changes, this file must change with it.

export type Role = 'administrator' | 'analyst' | 'investigator' | 'viewer'

export interface CurrentUser {
  id: string
  username: string
  email: string
  display_name: string
  role: Role
  organization_id: string
  is_active: boolean
  last_login_at: string | null
}

export interface User {
  id: string
  username: string
  email: string
  display_name: string
  role: Role
  organization_id: string
  is_active: boolean
  last_login_at: string | null
  created_at: string
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface DataSource {
  id: string
  organization_id: string
  name: string
  source_type: string
  description: string | null
  status: 'active' | 'inactive' | 'error'
  reliability_weight: number
  owner_team: string | null
  connection_mode: 'file_upload' | 'polling' | 'push' | 'internal' | string
  enabled: boolean
  last_error_category: string | null
  config_revision: number
  last_ingestion_attempt_at: string | null
  last_ingestion_success_at: string | null
  last_checkpoint_cursor: string | null
  last_checkpoint_at: string | null
  config_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ConnectivityCheckResult {
  ok: boolean
  detail: string | null
  applicable: boolean
}

export interface ConfigValidationResult {
  valid: boolean
  errors: string[]
}

export interface RawRecord {
  id: string
  organization_id: string
  source_id: string
  ingestion_job_id: string | null
  event_id: string | null
  external_record_id: string | null
  connector_type: string
  connector_version: string
  normalization_version: string
  schema_version: string
  content_fingerprint: string
  payload: Record<string, unknown>
  source_observed_at_raw: string | null
  received_at: string
  validation_status: 'valid' | 'invalid'
  validation_errors: Array<{ code: string; field: string | null; message: string }>
  validation_warnings: Array<{ code: string; field: string | null; message: string }>
  is_duplicate: boolean
  duplicate_of_raw_record_id: string | null
  duplicate_reason: string | null
  created_at: string
}

export interface EventCorrelation {
  id: string
  organization_id: string
  event_a_id: string
  event_b_id: string
  reasons: string[]
  rule_version: string
  temporal_delta_seconds: number | null
  spatial_delta_meters: number | null
  match_strength: number | null
  review_status: 'candidate' | 'confirmed' | 'rejected'
  reviewed_by_user_id: string | null
  reviewed_at: string | null
  correlation_batch_id: string | null
  created_at: string
}

export interface RecomputeCorrelationsResult {
  batch_id: string
  events_considered: number
  pairs_considered: number
  correlations_created: number
  already_existed: number
  rule_version: string
  time_window_seconds: number
  spatial_threshold_meters: number
}

export interface DataQualitySummary {
  total: number
  valid: number
  invalid: number
  duplicate: number
  accepted: number | null
  acceptance_rate: number | null
  rejection_rate: number | null
  duplicate_rate: number | null
  rejection_categories: Record<string, number>
  warning_categories: Record<string, number>
  source_id: string | null
  since: string | null
  until: string | null
}

export interface JobsSummary {
  total_jobs: number
  by_status: Record<string, number>
  accepted_total: number
  rejected_total: number
  duplicate_total: number
  source_id: string | null
  since: string | null
  until: string | null
}

export interface Asset {
  id: string
  organization_id: string
  name: string
  entity_type: string
  description: string | null
  status: string
  latitude: number | null
  longitude: number | null
  extra_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type SensorLifecycleStatus = 'registered' | 'active' | 'degraded' | 'offline' | 'maintenance' | 'retired'

export interface Sensor {
  id: string
  organization_id: string
  source_id: string | null
  name: string
  sensor_type: string
  status: 'active' | 'inactive' | 'fault' | 'unknown'
  last_seen_at: string | null
  latitude: number | null
  longitude: number | null
  capability_metadata: Record<string, unknown>
  config_version: string | null
  created_at: string
  updated_at: string

  // --- Section 3 ---------------------------------
  category: string | null
  description: string | null
  manufacturer: string | null
  model_name: string | null
  asset_id: string | null
  measurement_types: string[]
  measurement_units: Record<string, string>
  operating_range: Record<string, { min?: number; max?: number }>
  nominal_sampling_interval_seconds: number | null
  expected_data_format: string | null
  sensor_timezone: string
  lifecycle_status: SensorLifecycleStatus
  last_ingestion_success_at: string | null
  device_reported_status: string | null
  device_reported_status_at: string | null
  retired_at: string | null
}

export interface AegisEvent {
  id: string
  organization_id: string
  source_id: string
  external_id: string | null
  event_type: string
  title: string
  description: string | null
  observed_at: string
  ingested_at: string
  latitude: number | null
  longitude: number | null
  asset_id: string | null
  source_severity: string | null
  priority: string | null
  confidence: number | null
  attributes: Record<string, unknown>
  classification: string
  provenance: Record<string, unknown>
  processing_status: string
  data_origin: 'synthetic_demo' | 'user_upload' | 'external_source' | string
  ingestion_job_id: string | null
  created_at: string
  updated_at: string
}

export type ObservationValidationStatus = 'valid' | 'valid_with_warnings' | 'invalid' | 'stale' | 'duplicate' | 'incomplete' | 'out_of_range'

export interface Observation {
  id: string
  organization_id: string
  sensor_id: string | null
  source_id: string | null
  observed_at: string
  observation_type: string
  payload: Record<string, unknown>
  quality_metadata: Record<string, unknown>
  provenance: Record<string, unknown>
  processing_status: string
  data_origin: string
  latitude: number | null
  longitude: number | null
  created_at: string
  updated_at: string

  // --- Section 4 ---------------------------------
  ingested_at: string | null
  measurement_value: number | null
  unit: string | null
  validation_status: ObservationValidationStatus
  quality_flags: string[]
  source_record_id: string | null
  ingestion_job_id: string | null
  schema_version: string
  calibration_metadata: Record<string, unknown> | null
  uncertainty_metadata: Record<string, unknown> | null
}

// --- Multi-sensor data platform, analytics, anomalies ------

export interface SensorRawRecord {
  id: string
  organization_id: string
  source_id: string
  ingestion_job_id: string | null
  external_record_id: string | null
  connector_type: string
  connector_version: string
  content_fingerprint: string
  payload: Record<string, unknown>
  received_at: string
  validation_status: 'valid' | 'invalid'
  validation_errors: Array<{ code: string; field: string | null; message: string }>
  validation_warnings: Array<{ code: string; field: string | null; message: string }>
  is_duplicate: boolean
  duplicate_reason: string | null
}

export type AnomalySeverity = 'info' | 'low' | 'medium' | 'high'
export type AnomalyCategory = 'statistical_deviation' | 'data_quality' | 'sensor_health' | 'analyst_confirmed'
export type AnomalyReviewStatus = 'unreviewed' | 'confirmed_unusual' | 'dismissed_normal' | 'data_quality_issue'

export interface ObservationAnomaly {
  id: string
  organization_id: string
  sensor_id: string
  measurement_type: string
  observation_id: string | null
  window_start: string | null
  window_end: string | null
  detection_method: string
  method_version: string
  config: Record<string, unknown>
  observed_value: number | null
  observed_summary: Record<string, unknown>
  baseline_summary: Record<string, unknown> | null
  explanation: string
  severity: AnomalySeverity
  category: AnomalyCategory
  quality_flags: string[]
  review_status: AnomalyReviewStatus
  reviewed_by_user_id: string | null
  reviewed_at: string | null
  review_note: string | null
  created_at: string
}

export interface AnomalyRunResult {
  created: ObservationAnomaly[]
  already_known: ObservationAnomaly[]
  insufficient_baseline: Record<string, string>
}

export interface TimeSeriesPoint {
  observation_id: string
  observed_at: string
  value: number | null
  unit: string | null
  validation_status: ObservationValidationStatus
  quality_flags: string[]
}

export interface TimeSeriesResponse {
  sensor_id: string
  measurement_type: string
  unit: string | null
  since: string
  until: string
  points: TimeSeriesPoint[]
  total_in_range: number
  returned_count: number
  is_downsampled: boolean
  aggregation_note: string | null
}

export interface GapSummary {
  gap_count: number
  max_gap_seconds: number | null
  missing_frame_like: boolean
}

export interface DescriptiveStatistics {
  measurement_type: string
  unit: string | null
  valid_count: number
  invalid_count: number
  minimum: number | null
  maximum: number | null
  mean: number | null
  median: number | null
  stdev_sample: number | null
  percentiles: Record<string, number | null>
  latest_valid_value: number | null
  latest_valid_observed_at: string | null
  rate_of_change_per_second: number | null
  gap_summary: GapSummary | null
  insufficient_sample: boolean
  method_version: string
}

export interface ConnectivityHealth {
  status: 'never_connected' | 'connected' | 'missed_heartbeat' | 'offline'
  last_valid_observation_at: string | null
  last_ingestion_success_at: string | null
  explanation: string
}

export interface MeasurementQualityHealth {
  status: 'insufficient_data' | 'good' | 'degraded'
  sample_size: number
  invalid_count: number
  invalid_rate: number | null
  warning_rate: number | null
  explanation: string
}

export interface AnomalyStatusHealth {
  unresolved_count: number
  by_severity: Record<string, number>
  explanation: string
}

export interface DeviceReportedHealth {
  status: string | null
  as_of: string | null
  explanation: string
}

export interface SensorHealth {
  sensor_id: string
  as_of: string
  rule_version: string
  connectivity: ConnectivityHealth
  measurement_quality: MeasurementQualityHealth
  anomaly_status: AnomalyStatusHealth
  device_reported: DeviceReportedHealth
}

export interface CrossSourceComparison {
  method_version: string
  observation_a_id: string
  observation_b_id: string
  sensor_a_id: string | null
  sensor_b_id: string | null
  measurement_type_a: string
  measurement_type_b: string
  same_measurement_type: boolean
  unit_a: string | null
  unit_b: string | null
  units_compatible: boolean
  value_a: number | null
  value_b: number | null
  value_b_converted_to_unit_a: number | null
  delta: number | null
  tolerance: number | null
  conflicting: boolean | null
  missing_a: boolean
  missing_b: boolean
  time_gap_seconds: number
  observed_at_a: string
  observed_at_b: string
  provenance_a: Record<string, unknown>
  provenance_b: Record<string, unknown>
  explanation: string
}

export interface Investigation {
  id: string
  organization_id: string
  title: string
  description: string | null
  status: 'open' | 'active' | 'closed' | string
  priority: 'low' | 'normal' | 'high' | 'urgent' | string
  assigned_user_id: string | null
  linked_event_ids: string[]
  evidence_refs: string[]
  review_status: 'not_reviewed' | 'reviewed' | string
  resolution_notes: string | null
  created_at: string
  updated_at: string
}

export interface RiskAssessment {
  id: string
  organization_id: string
  subject_type: string
  subject_id: string
  assessed_at: string
  method: string
  model_record_id: string | null
  score: number
  score_scale: string
  confidence: number | null
  contributing_factors: Array<{ factor: string; weight: number }>
  evidence_refs: string[]
  explanation: string | null
  human_review_status: 'pending' | 'confirmed' | 'overridden' | 'dismissed'
  reviewer_user_id: string | null
  reviewed_at: string | null
  reviewer_notes: string | null
  data_origin: string
  created_at: string
}

export interface IngestionJob {
  id: string
  organization_id: string
  source_id: string
  created_by_user_id: string | null
  job_type: string
  status: 'running' | 'completed' | 'completed_with_errors' | 'failed'
  started_at: string
  completed_at: string | null
  accepted_count: number
  rejected_count: number
  skipped_count: number
  duplicate_count: number
  error_summary: Array<{ index?: number; error: string }>
  trigger_type: 'manual' | 'retry' | 'api' | string
  retry_count: number
  correlation_id: string | null
  created_at: string
}

export interface AuditRecord {
  id: string
  organization_id: string | null
  actor_user_id: string | null
  action: string
  target_type: string | null
  target_id: string | null
  outcome: string
  request_id: string | null
  context_metadata: Record<string, unknown>
  created_at: string
}

export interface DashboardSummary {
  total_events: number
  events_last_24h: number
  open_investigations: number
  active_sources: number
  active_sensors: number
  pending_risk_reviews: number
  ingestion_jobs_last_24h: number
  synthetic_data_present: boolean
}

export interface ReadinessResponse {
  status: 'ready' | 'not_ready'
  checks: { database: 'ok' | 'error'; media_storage?: 'ok' | 'error'; model_runtime?: 'ok' | 'error' }
}

// --- Fusion, evidence, relationships, conflicts, assessments ----

export interface Evidence {
  id: string
  organization_id: string
  evidence_type: 'observation' | 'ingestion_record' | 'sensor_observation' | 'report' | 'analyst_note' | 'document' | 'media_reference' | string
  title: string
  summary: string | null
  event_id: string | null
  raw_record_id: string | null
  observation_id: string | null
  content: string | null
  external_reference_uri: string | null
  integrity_hash: string | null
  detection_result_id?: string | null
  created_by_user_id: string | null
  created_at: string
  updated_at: string
}

export interface EvidenceRelationship {
  id: string
  organization_id: string
  source_event_id: string | null
  source_evidence_id: string | null
  target_event_id: string | null
  target_evidence_id: string | null
  relationship_type: string
  origin: 'rule_based' | 'model_assisted' | 'analyst_created' | string
  explanation: string
  supporting_metadata: Record<string, unknown>
  review_status: 'candidate' | 'confirmed' | 'rejected' | 'uncertain' | string
  reviewed_by_user_id: string | null
  reviewed_at: string | null
  review_note: string | null
  is_reversed: boolean
  last_reversed_at: string | null
  created_by_user_id: string | null
  fusion_batch_id: string | null
  created_at: string
}

export interface ReviewHistoryEntry {
  id: string
  action: string
  actor_user_id: string | null
  outcome: string
  context_metadata: Record<string, unknown>
  created_at: string
}

export interface Conflict {
  id: string
  organization_id: string
  event_a_id: string
  event_b_id: string
  correlation_id: string | null
  conflicting_fields: Array<{ field: string; rule: string; value_a?: unknown; value_b?: unknown }>
  conflict_rule_version: string
  review_status: 'unresolved' | 'explained' | 'accepted' | 'corrected' | 'superseded' | string
  resolved_by_user_id: string | null
  resolved_at: string | null
  resolution_note: string | null
  fusion_batch_id: string | null
  created_at: string
}

export interface DetectConflictsResult {
  batch_id: string
  pairs_considered: number
  conflicts_created: number
  conflicts_updated: number
  rule_version: string
}

export interface Assessment {
  id: string
  organization_id: string
  title: string
  question: string
  scope_description: string | null
  scope_start: string | null
  scope_end: string | null
  summary: string | null
  assumptions: string[]
  information_gaps: string[]
  confidence_level: 'low' | 'moderate' | 'high' | null
  confidence_rationale: string | null
  status: 'draft' | 'in_review' | 'published' | 'archived' | string
  version: number
  author_user_id: string | null
  superseded_by_assessment_id: string | null
  created_at: string
  updated_at: string
}

export interface AssessmentRevision {
  id: string
  assessment_id: string
  version: number
  snapshot: Record<string, unknown>
  changed_by_user_id: string | null
  change_note: string | null
  created_at: string
}

export interface AssessmentEvidenceLink {
  id: string
  assessment_id: string
  event_id: string | null
  evidence_id: string | null
  role: 'supporting' | 'contradicting' | string
  note: string | null
  created_at: string
}

export interface FusionJob {
  id: string
  organization_id: string
  status: 'running' | 'completed' | 'failed' | string
  triggered_by_user_id: string | null
  rule_version: string
  parameters: Record<string, unknown>
  events_considered: number
  correlations_created: number
  conflicts_created: number
  started_at: string
  finished_at: string | null
  error_message: string | null
  created_at: string
}

export interface GraphNode {
  id: string
  type: 'event' | 'evidence' | 'assessment' | string
  label: string
  data: Record<string, unknown>
}

export interface GraphEdge {
  id: string
  type: 'correlation' | 'relationship' | 'conflict' | 'assessment_link' | string
  origin: string | null
  source: { type: string; id: string }
  target: { type: string; id: string }
  reasons: string[] | null
  relationship_type: string | null
  conflicting_fields: unknown[] | null
  role: string | null
  explanation: string | null
  match_strength: number | null
  review_status: string | null
}

export interface GraphResponse {
  seed: { type: string; id: string }
  nodes: GraphNode[]
  edges: GraphEdge[]
  truncated: boolean
  max_depth: number
  max_nodes: number
}

// --- Computer vision infrastructure ------------------------

export interface MediaAsset {
  id: string
  organization_id: string
  media_type: 'image' | 'video'
  status: 'stored' | 'rejected'
  rejection_reason: string | null
  declared_filename: string
  detected_mime_type: string
  content_hash: string
  byte_size: number
  width_px: number | null
  height_px: number | null
  duration_seconds: number | null
  frame_count: number | null
  fps: number | null
  uploaded_by_user_id: string | null
  created_at: string
  updated_at: string
}

export interface CVModel {
  id: string
  name: string
  version: string
  model_type: string
  task_type: 'object_detection' | string | null
  adapter_key: string | null
  supported_media_types: string[]
  status: 'registered' | 'active' | 'deprecated' | 'retired' | string
  evaluation_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface InferenceJob {
  id: string
  organization_id: string
  media_asset_id: string
  model_record_id: string
  job_type: 'image_detection' | 'video_frame_analysis' | string
  status: 'pending' | 'running' | 'completed' | 'failed' | string
  parameters: Record<string, unknown>
  frames_processed: number
  detections_created: number
  idempotency_key: string | null
  retry_count: number
  retried_from_job_id: string | null
  triggered_by_user_id: string | null
  started_at: string | null
  finished_at: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface DetectionResult {
  id: string
  organization_id: string
  inference_job_id: string
  media_asset_id: string
  model_record_id: string
  schema_version: string
  frame_index: number | null
  frame_timestamp_seconds: number | null
  class_label: string
  confidence: number
  bbox_x_min: number
  bbox_y_min: number
  bbox_x_max: number
  bbox_y_max: number
  review_status: 'unreviewed' | 'confirmed' | 'rejected'
  reviewed_by_user_id: string | null
  reviewed_at: string | null
  review_note: string | null
  created_at: string
}

export type EvaluationDataset = 'synthetic_single_rectangle_fixture' | 'coco_val2017_subset'

export interface ModelEvaluationRun {
  id: string
  organization_id: string
  model_record_id: string
  dataset_name: string
  dataset_version: string
  is_synthetic: boolean
  sample_count: number
  iou_match_threshold: number
  precision: number
  recall: number
  f1_score: number
  mean_iou: number
  metrics_detail: Record<string, unknown>
  notes: string | null
  evaluated_by_user_id: string | null
  evaluated_at: string
}

// --- Object tracking, lifecycle, motion analytics, evaluation ----

// Sequence-scoped only -- see app/models/track.py. A track_id/state here
// is never evidence of a real-world identity, and never implies a
// cross-video or cross-camera identity.
export type TrackState = 'tentative' | 'confirmed' | 'missing' | 'reacquired' | 'ended' | 'rejected'

export interface TrackingJob {
  id: string
  organization_id: string
  media_asset_id: string
  inference_job_id: string
  tracker_key: string
  tracker_version: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  result_schema_version: string
  config: Record<string, unknown>
  frames_considered: number
  frames_processed: number
  detections_considered: number
  tracks_created: number
  idempotency_key: string | null
  retry_count: number
  retried_from_job_id: string | null
  triggered_by_user_id: string | null
  started_at: string | null
  finished_at: string | null
  processing_duration_seconds: number | null
  error_category: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface LifecycleEvent {
  frame_index: number
  timestamp_seconds: number
  from_state: TrackState | null
  to_state: TrackState
  reason: string
}

export interface Track {
  id: string
  organization_id: string
  tracking_job_id: string
  sequence_track_id: string
  class_label: string | null
  first_frame_index: number
  last_frame_index: number
  first_timestamp_seconds: number
  last_timestamp_seconds: number
  matched_observations_count: number
  missed_frames_count: number
  state: TrackState
  quality_summary: Record<string, unknown>
  lifecycle_events: LifecycleEvent[]
  created_at: string
}

export interface TrackObservation {
  id: string
  track_id: string
  detection_result_id: string
  media_asset_id: string
  frame_index: number
  frame_timestamp_seconds: number
  bbox_x_min: number
  bbox_y_min: number
  bbox_x_max: number
  bbox_y_max: number
  class_label: string
  confidence: number
  association_method: string
  association_cost: number | null
  observation_state: 'matched'
  created_at: string
}

export interface TrackingJobSummary {
  tracks_by_state: Record<string, number>
  total_tracks: number
  mean_track_duration_seconds: number
  total_observations: number
}

export interface TrackMotionStep {
  from_frame_index: number
  to_frame_index: number
  elapsed_seconds: number
  center_from_px: [number, number]
  center_to_px: [number, number]
  displacement_px: number
  direction_degrees: number | null
}

export interface TrackMotion {
  unit_note: string
  observation_count: number
  duration_seconds: number
  total_path_length_px: number
  net_displacement_px: number
  bbox_area_px_first: number
  bbox_area_px_last: number
  bbox_area_change_ratio: number | null
  missed_sampled_frame_count: number
  missing_frame_indices: number[]
  fragmentation_count: number
  steps: TrackMotionStep[]
}

export interface TrackerConfigOption {
  tracker_key: string
  tracker_version: string
  is_deterministic: boolean
}

export interface TrackerConfigDefaults {
  available_trackers: TrackerConfigOption[]
  default_tracker_key: string
  min_iou_threshold: number
  max_missed_frames: number
  min_hits_to_confirm: number
  require_class_match: boolean
  max_active_tracks_per_job: number
}

export type AnnotationType = 'reviewed' | 'possible_error' | 'fragmented_track' | 'false_association' | 'uncertain_association' | 'note'

export interface TrackAnnotation {
  id: string
  track_id: string
  annotation_type: AnnotationType
  note: string | null
  created_by_user_id: string | null
  supersedes_annotation_id: string | null
  superseded_at: string | null
  created_at: string
}

export interface TrackingEvaluationRun {
  id: string
  organization_id: string
  tracker_key: string
  tracker_version: string
  config: Record<string, unknown>
  dataset_name: string
  dataset_version: string
  is_synthetic: boolean
  sequence_count: number
  track_precision: number
  track_recall: number
  identity_switches: number
  fragmentation_count: number
  mostly_tracked_ratio: number
  mostly_lost_ratio: number
  mean_association_iou: number
  metrics_detail: Record<string, unknown>
  notes: string | null
  evaluated_by_user_id: string | null
  evaluated_at: string
}

// --- Geospatial intelligence --------------------------------
// Mirrors backend/app/schemas/geospatial.py exactly.

export type GeoRecordType = 'event' | 'sensor' | 'observation' | 'asset'

export interface LocatedRecord {
  record_type: GeoRecordType
  record_id: string
  title: string
  summary: string | null
  source_id: string | null
  sensor_id: string | null
  latitude: number
  longitude: number
  coordinate_reference_system: string
  location_origin: string | null
  location_validation_status: string | null
  location_uncertainty_m: number | null
  altitude_m: number | null
  altitude_reference: string | null
  timestamp: string
  timestamp_type: string
  is_synthetic: boolean | null
  quality_findings: string[]
  distance_m: number | null
}

export interface BoundsSearched {
  min_lat: number
  max_lat: number
  min_lon: number
  max_lon: number
  crossed_antimeridian: boolean
}

export interface TimeRangeSearched {
  since: string | null
  until: string | null
  timestamp_type: string
}

export interface GeospatialQueryResult {
  items: LocatedRecord[]
  total_matched: number
  returned_count: number
  truncated: boolean
  max_results: number
  bounds_searched: BoundsSearched | null
  radius_km: number | null
  center_latitude: number | null
  center_longitude: number | null
  time_range_searched: TimeRangeSearched | null
  record_types_searched: GeoRecordType[]
  missing_or_invalid_location_count: number
}

export interface LocationFinding {
  code: string
  is_error: boolean
  explanation: string
}

export interface LocationQualityRecord {
  record_type: GeoRecordType
  record_id: string
  title: string
  latitude: number | null
  longitude: number | null
  coordinate_reference_system: string
  location_validation_status: string | null
  findings: LocationFinding[]
}

export interface LocationQualitySummary {
  record_types_checked: GeoRecordType[]
  total_records_checked: number
  missing_count: number
  invalid_range_count: number
  non_finite_count: number
  unsupported_crs_count: number
  valid_count: number
  uncertainty_unavailable_count: number
  stale_count: number
  by_record_type: Record<string, Record<string, number | boolean>>
}

export interface SpatialRelationshipCandidate {
  relationship_id: string
  source_ref_type: string
  source_ref_id: string
  source_record_type: GeoRecordType
  source_record_id: string
  target_ref_type: string
  target_ref_id: string
  target_record_type: GeoRecordType
  target_record_id: string
  relationship_type: string
  distance_m: number | null
  time_difference_seconds: number | null
  rule_version: string
  explanation: string
  review_status: string
  origin: string
  source_location_quality: string | null
  target_location_quality: string | null
  created_at: string
}

export interface SpatialRelationshipRunResult {
  candidates_created: number
  candidates_already_known: number
  pairs_considered: number
  candidates_considered: number
  candidates_truncated: boolean
  rule_version: string
  distance_threshold_m: number
  time_window_seconds: number
}

export interface TimeBucketCount {
  bucket_start: string
  bucket_end: string
  count: number
}

export interface TimeBucketCountsResult {
  buckets: TimeBucketCount[]
  is_approximate: boolean
}

export interface TemporalGap {
  record_type: GeoRecordType
  gap_start: string
  gap_end: string
  gap_seconds: number
}

export interface TemporalGapsResult {
  gaps: TemporalGap[]
  is_approximate: boolean
}

export interface SpatialGridCell {
  min_lat: number
  max_lat: number
  min_lon: number
  max_lon: number
  count: number
  record_types: Record<string, number>
}

export interface SpatialGridResult {
  cells: SpatialGridCell[]
  is_approximate: boolean
}

export interface GeospatialOverview {
  located_records_total: number
  located_records_by_type: Record<string, number>
  missing_or_invalid_location_total: number
  recent_located_records: LocatedRecord[]
  spatial_relationship_candidates_unreviewed: number
  location_conflicts_unreviewed: number
  temporal_coverage_earliest: string | null
  temporal_coverage_latest: string | null
  data_quality_summary: LocationQualitySummary
}

// NOTE: the export endpoints (GET /geospatial/export/geojson|csv) return
// the raw file bytes directly (Content-Disposition: attachment), not a
// JSON-wrapped envelope -- api.client's geospatial.exportGeojson/exportCsv
// return a Blob + the server-suggested filename, there is no
// GeospatialExportResult response type to model here.

// --- Edge AI offline-first operation ---------------------

export type DeviceAdministrativeStatus = 'pending' | 'active' | 'suspended' | 'revoked' | 'maintenance' | 'decommissioned'
export type DeviceConnectivityState = 'online' | 'offline' | 'unknown'
// Server-authoritative, live-computed presence -- distinct from
// connectivity_state (the device's own self-report). Always show this
// as the primary signal in the UI, connectivity_state as secondary.
export type DevicePresenceState = 'online' | 'stale' | 'offline' | 'unknown'

export interface Device {
  id: string
  device_identifier: string
  device_name: string
  device_type: string
  deployment_label: string | null
  software_version: string | null
  protocol_version: string | null
  api_key_prefix: string | null
  capabilities: string[]
  inference_backends: string[]
  model_manifest: Record<string, unknown>
  connectivity_state: DeviceConnectivityState
  local_storage_status: Record<string, unknown> | null
  last_seen_at: string | null
  last_sync_at: string | null
  last_health_report_at: string | null
  config_version: string | null
  sync_status: string
  administrative_status: DeviceAdministrativeStatus
  revoked_at: string | null
  revoked_reason: string | null
  metadata_note: string | null
  created_at: string
  // Live-computed by the backend on every read, never a stale column
  // (see backend/app/schemas/device.py's DeviceResponse docstring).
  pending_sync_count: number
  unresolved_conflict_count: number

  // --- ----------------------------------------------
  site_id: string | null
  config_revision: number
  config_baseline_id: string | null
  current_config: Record<string, unknown>
  last_resource_metrics: Record<string, unknown> | null
  presence_state: DevicePresenceState
}

export interface DeviceRegistrationResult {
  // `api_key` is the plaintext secret and is returned exactly once --
  // at registration or key-rotation time -- and never retrievable
  // again afterward. Never persist this beyond the one-time dialog.
  device: Device
  api_key: string
}

export interface DeviceHealthReport {
  id: string
  device_id: string
  reported_at: string
  connectivity_state: DeviceConnectivityState
  resource_metrics: Record<string, unknown> | null
  queue_depth: number | null
  pending_sync_count: number | null
  model_status: Record<string, unknown> | null
  software_version: string | null
  runtime_capabilities: string[] | null
  created_at: string
}

export type SyncRecordStatus =
  | 'queued'
  | 'syncing'
  | 'synced'
  | 'retryable_failure'
  | 'permanent_failure'
  | 'conflict'
  | 'quarantined'
  | 'cancelled'

export interface SyncRecord {
  id: string
  device_id: string
  message_id: string
  idempotency_key: string
  batch_id: string | null
  protocol_version: string
  schema_version: string
  record_type: string
  client_record_id: string
  base_revision: number | null
  revision: number | null
  payload_hash: string | null
  source_created_at: string
  queued_at: string
  processed_at: string | null
  acknowledged_at: string | null
  sync_status: SyncRecordStatus
  retry_count: number
  next_retry_at: string | null
  last_error_category: string | null
  last_error_message: string | null
  supersedes_sync_record_id: string | null
  created_at: string
}

export interface SyncQueueStatusCount {
  sync_status: string
  count: number
}

export interface SyncQueueSummary {
  // Every count here is a real query result, never a fabricated/sample
  // figure -- a field that genuinely could not be computed is left out
  // (Optional) rather than zeroed. See backend/app/schemas/edge_sync.py's
  // SyncQueueSummaryResponse docstring.
  total_records: number
  by_status: SyncQueueStatusCount[]
  oldest_pending_age_seconds: number | null
  unresolved_conflict_count: number
  quarantined_count: number
  devices_with_pending_records: number
}

export type SyncConflictResolutionStatus = 'unresolved' | 'resolved'
export type SyncConflictResolutionStrategy = 'keep_central' | 'keep_local' | 'merged'

export interface SyncConflict {
  id: string
  device_id: string
  sync_record_id: string
  record_type: string
  client_record_id: string
  conflict_reason: string
  local_version: Record<string, unknown>
  central_version: Record<string, unknown>
  resolution_status: SyncConflictResolutionStatus
  resolution_strategy: SyncConflictResolutionStrategy | null
  resolved_by_user_id: string | null
  resolved_at: string | null
  resolution_note: string | null
  created_at: string
}

// --- Enterprise edge fleet management -----------------------
// Mirrors backend/app/schemas/fleet.py exactly.

export interface FleetSite {
  id: string
  name: string
  description: string | null
  latitude: number | null
  longitude: number | null
  created_at: string
}

export interface FleetSiteSummary {
  site_id: string
  site_name: string
  device_count: number
  presence_counts: Record<string, number>
  administrative_status_counts: Record<string, number>
  open_alert_count: number
}

export interface DeviceCapability {
  capability_key: string
  supported: boolean
  installed: boolean
  available_and_ready: boolean
  // null = never verified -- NOT the same as false (verified unhealthy).
  healthy: boolean | null
  last_verified_at: string | null
  last_reported_at: string | null
}

export interface FleetCapabilitySummaryEntry {
  capability_key: string
  device_count: number
  supported_count: number
  installed_count: number
  available_and_ready_count: number
  healthy_count: number
  recently_verified_count: number
}

export interface DeviceConfigBaseline {
  id: string
  name: string
  version: number
  expected_config: Record<string, unknown>
  description: string | null
  created_at: string
}

export interface DeviceConfigDrift {
  // false = no baseline assigned yet, or it was deleted -- render as
  // "Not evaluated", never as "no drift".
  evaluated: boolean
  has_drift: boolean | null
  baseline_id: string | null
  baseline_version?: number | null
  differences: Array<{ key: string; current_value: unknown; expected_value: unknown }>
}

export interface DeviceConfigState {
  current_config: Record<string, unknown>
  config_revision: number
  config_baseline_id: string | null
  drift: DeviceConfigDrift
}

export type InfraAlertSeverity = 'info' | 'warning' | 'serious' | 'critical'
export type InfraAlertStatus = 'open' | 'acknowledged' | 'resolved' | 'reopened'

export interface InfrastructureAlert {
  id: string
  device_id: string | null
  alert_type: string
  severity: InfraAlertSeverity
  status: InfraAlertStatus
  dedup_key: string
  title: string
  evidence: Record<string, unknown>
  explanation: string | null
  occurrence_count: number
  first_detected_at: string
  last_evaluated_at: string
  acknowledged_at: string | null
  acknowledged_by_user_id: string | null
  resolved_at: string | null
  resolved_by_user_id: string | null
  resolution_note: string | null
  created_at: string
}

export interface FleetOverview {
  as_of: string
  total_devices: number
  presence_counts: Record<string, number>
  administrative_status_counts: Record<string, number>
  devices_with_assigned_baseline: number
  baseline_assignment_pct: number | null
  open_alerts_by_severity: Record<string, number>
  total_open_alerts: number
  unresolved_sync_conflicts: number
}

export interface LifecyclePreview {
  current_status: string
  target_status: string
  is_legal: boolean
  is_consequential: boolean
  impact_notes: string[]
}

// ---------------------------------------------------------------------
// Explainable AI, model evaluation, assessment scoring/review
// ---------------------------------------------------------------------
export interface MetricValue {
  value: number | null
  defined: boolean
  reason: string | null
  definition: string
  excluded_classes?: string[]
}

export interface PerClassMetrics {
  support: number
  predicted_count: number
  precision: MetricValue
  recall: MetricValue
  f1: MetricValue
}

export interface ClassificationReport {
  labels: string[]
  labelled_sample_count: number
  excluded_missing_label: number
  confusion_matrix: number[][]
  accuracy: MetricValue
  macro_f1: MetricValue
  per_class: Record<string, PerClassMetrics>
  class_distribution: Record<string, number>
  warnings: string[]
}

export interface ProbabilityReport {
  positive_label: string
  scored_sample_count: number
  excluded_missing_label: number
  excluded_missing_probability: number
  brier_score: MetricValue
  log_loss: MetricValue
  roc_auc: MetricValue
  warnings: string[]
}

export interface ClassificationEvaluation {
  id: string
  model_record_id: string
  model_version: string
  dataset_name: string
  dataset_version: string
  dataset_reference: string | null
  is_synthetic: boolean
  performance_claim: string
  sample_count: number
  excluded_missing_label: number
  evaluation_config: Record<string, unknown>
  metric_definitions: Record<string, string>
  results: { classification: ClassificationReport; probability: ProbabilityReport | null } | null
  warnings: string[]
  status: 'completed' | 'failed'
  error_message: string | null
  evaluated_by_user_id: string | null
  evaluated_at: string
}

export interface EvaluationOverviewRow {
  kind: 'classification' | 'detection' | 'tracking'
  id: string
  model_record_id: string | null
  model_name: string | null
  model_version: string | null
  dataset_name: string
  dataset_version: string
  is_synthetic: boolean | null
  status: string
  headline_metrics: Record<string, number | null>
  evaluated_at: string
}

export interface EvaluationSampleInput {
  sample_ref?: string | null
  true_label: string | null
  predicted_label: string
  positive_probability?: number | null
}

export interface ClassificationEvaluationRequest {
  model_record_id: string
  model_version?: string | null
  dataset_name: string
  dataset_version: string
  dataset_reference?: string | null
  is_synthetic: boolean
  labels?: string[] | null
  positive_label?: string | null
  samples: EvaluationSampleInput[]
}

export type ModelOutputType = 'detection_result' | 'risk_assessment'

export interface DataQualityIndicator {
  code: string
  severity: 'info' | 'warning' | 'error'
  message: string
}

export interface RecordRef {
  type: string
  id: string
  label: string | null
}

export interface ModelOutput {
  schema_version: string
  output_type: ModelOutputType
  output_id: string
  organization_id: string
  model: { model_record_id: string | null; name: string; version: string; adapter_key: string | null; evaluation_metadata: Record<string, unknown> }
  input_refs: RecordRef[]
  source_refs: RecordRef[]
  prediction: Record<string, unknown>
  confidence: number | null
  confidence_provided: boolean
  confidence_note: string | null
  processed_at: string
  execution_status: 'completed' | 'failed' | 'unknown'
  data_quality: DataQualityIndicator[]
  features: Record<string, unknown>
  explanation_metadata: Record<string, unknown>
  supporting_records: RecordRef[]
  review_status: string | null
}

export interface ModelOutputPage extends Page<ModelOutput> {
  skipped_invalid: number
}

export interface ExplanationMethodInfo {
  method_key: string
  label: string
  explanation_kind: string
  supported: boolean
  limitation: string | null
}

export interface ExplanationItem {
  name: string
  value?: unknown
  weight?: number
  contribution?: number
  detail?: unknown
}

export interface Explanation {
  output_type: string
  output_id: string
  supported: boolean
  method_key: string | null
  label: string | null
  explanation_kind: string | null
  items: ExplanationItem[]
  method_detail: string | null
  interpretation_note: string | null
  limitation: string | null
  available_methods: ExplanationMethodInfo[]
  data_quality: DataQualityIndicator[]
}

export interface ScoreFactor {
  key: string
  label: string
  input_value: unknown
  points: number
  max_points: number
  rationale: string
}

export interface AssessmentScoreSnapshot {
  id: string
  assessment_id: string
  assessment_version: number
  rule_key: string
  rule_version: string
  rule_config: Record<string, unknown>
  score: number
  score_scale: string
  priority_band: 'low' | 'medium' | 'high'
  factors: ScoreFactor[]
  distinct_concepts: Record<string, Record<string, unknown>>
  evidence_considered: Array<Record<string, unknown>>
  data_quality_limitations: Array<{ code: string; message: string }>
  conflicts: Array<{ conflict_id: string; event_a_id: string; event_b_id: string; conflicting_fields: unknown[] }>
  missing_information: Array<{ source: string; description: string }>
  computed_at: string
  computed_by_user_id: string | null
  advisory_notice: string
}

export type ReviewDecision = 'accepted' | 'rejected' | 'further_review_requested'

export interface AssessmentReviewRecord {
  id: string
  assessment_id: string
  assessment_version: number
  score_snapshot_id: string | null
  decision: ReviewDecision
  notes: string
  change_reason: string | null
  information_flags: string[]
  advisory_score_at_review: number | null
  advisory_band_at_review: string | null
  reviewer_user_id: string | null
  supersedes_review_id: string | null
  created_at: string
}

export interface ReviewComparison {
  available: boolean
  note: string
  advisory_score_at_review?: number | null
  advisory_band_at_review?: string | null
  human_decision?: string
  expected_by_band?: string | null
  agreement?: boolean | null
  review_is_for_current_version?: boolean
}

export interface ReviewSummary {
  assessment_id: string
  current_assessment_version: number
  review_status: 'unreviewed' | ReviewDecision
  latest_review: AssessmentReviewRecord | null
  latest_score: AssessmentScoreSnapshot | null
  comparison: ReviewComparison
  history: AssessmentReviewRecord[]
}

export interface ScoringRules {
  score_scale: string
  bands: Array<{ band: string; min_score: number }>
  allowed_inputs: string[]
  advisory_notice: string
  rules: Record<string, { version: string; description: string; config: Record<string, unknown> }>
}
