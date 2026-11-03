// Types mirror the real /api/v1/mlops and /api/v1/observability responses
// (backend/app/schemas/mlops.py and the service serializers). Nothing here is
// sample data.
import type { Page } from './api'

export type TaskType = 'object_detection' | 'classification'
export type LifecycleState = 'registered' | 'review_required' | 'approved' | 'deprecated' | 'archived'
export type TransitionAction = 'request_review' | 'reject_review' | 'approve' | 'revoke_approval' | 'deprecate' | 'reactivate' | 'archive'
export type SignalSeverity = 'info' | 'warning' | 'serious' | 'critical'
export type SignalStatus = 'open' | 'acknowledged' | 'resolved'

export interface ArtifactBrief { kind: string; available: boolean; reason: string | null; digest_checked?: boolean; digest_match?: boolean | null }

export interface EvaluationSummary {
  status: 'none' | 'running' | 'failed' | 'stale' | 'review_needed' | 'passed'
  latest_run_id: string | null
  latest_run_at: string | null
  latest_succeeded_run_id: string | null
  latest_succeeded_at: string | null
  run_count: number
  metrics: Record<string, number | null>
}

export interface ModelVersion {
  id: string
  name: string
  version: string
  task_type: TaskType | null
  model_type: string
  lifecycle_state: LifecycleState
  legacy_status: string
  adapter_key: string | null
  supported_media_types: string[]
  artifact_reference: string | null
  artifact_digest: string | null
  artifact: ArtifactBrief
  scope: 'platform' | 'organization'
  owned_by_your_organization: boolean
  created_at: string
  evaluation: EvaluationSummary
  input_schema_version?: string | null
  output_schema_version?: string | null
  framework_metadata?: Record<string, unknown>
  release_notes?: string | null
  documentation_ref?: string | null
  created_by_user_id?: string | null
  serving_note?: string
}

export interface ModelFamily {
  name: string
  version_count: number
  latest_version: string | null
  task_types: string[]
  lifecycle_counts: Record<string, number>
  latest_registered_at: string
}

export interface LifecycleEvent {
  id: string
  action: string
  from_state: string | null
  to_state: string
  actor_user_id: string | null
  actor_scope: 'your_organization' | 'other_organization' | 'system'
  reason: string | null
  evidence: Record<string, unknown>
  created_at: string
}

export interface MetricValue {
  value: number | null
  defined: boolean
  n?: number | null
  ci95?: [number, number] | null
  reason?: string | null
}

export interface ExperimentRun {
  id: string
  model_record_id: string
  model_version: string
  task: TaskType
  experiment_name: string
  purpose: string | null
  status: 'running' | 'succeeded' | 'failed'
  dataset_name: string
  dataset_version: string
  is_synthetic: boolean
  dataset_fingerprint: string
  config_fingerprint: string
  run_fingerprint: string
  started_at: string
  completed_at: string | null
  duration_ms: number | null
  metrics: Record<string, MetricValue> | null
  sample_count: number | null
  error_category: string | null
  error_message: string | null
  config?: Record<string, unknown>
  methodology?: string | null
  limitations?: string | null
  reproducibility?: Record<string, unknown>
  performance_claim?: string
}

export interface ComparisonRow {
  metric: string
  direction: 'higher_is_better' | 'lower_is_better'
  baseline: { value: number | null; n: number | null; ci95: [number, number] | null }
  candidate: { value: number | null; n: number | null; ci95: [number, number] | null }
  comparable: boolean
  absolute_difference: number | null
  relative_difference: number | null
  change: 'improved' | 'regressed' | 'unchanged' | 'not_comparable'
  distinguishable_at_95: boolean | null
  exceeds_review_threshold: boolean
  review_threshold: number
  note: string | null
}

export type Comparison =
  | { status: 'no_baseline'; message: string }
  | { status: 'is_baseline'; message: string }
  | {
      status: 'compared'
      metrics: ComparisonRow[]
      summary: { improved: number; regressed: number; unchanged: number; not_comparable: number; review_recommended: boolean; statement: string }
      caveats: string[]
      sample_counts: { baseline: number | null; candidate: number | null }
      small_sample_warning: boolean
    }

export interface HistoryPoint {
  run_id: string
  at: string
  model_version: string
  value: number
  n: number | null
  ci95: [number, number] | null
  is_synthetic: boolean
  dataset: string
}
export interface MetricHistory {
  metric: string
  task: string
  window_days: number
  points: HistoryPoint[]
  runs_without_this_metric_defined: number
  comparable_datasets: boolean
  note: string | null
}

export interface ReviewSignal {
  id: string
  category: string
  severity: SignalSeverity
  status: SignalStatus
  title: string
  summary: string
  subsystem: string
  model_record_id: string | null
  model_name: string | null
  model_version: string | null
  experiment_run_id: string | null
  snapshot_id: string | null
  observed_value: number | null
  threshold_value: number | null
  evidence: Record<string, unknown>
  limitations: string | null
  occurrence_count: number
  first_seen_at: string
  last_seen_at: string
  assigned_to_user_id: string | null
  acknowledged_at: string | null
  resolved_at: string | null
  resolution_notes: string | null
  advisory_notice: string
}
export interface SignalPage extends Page<ReviewSignal> {
  counts: { by_status: Record<string, number>; unresolved_by_severity: Record<string, number> }
}

export interface MonitoringSnapshot {
  id: string
  model_record_id: string
  kind: 'reference' | 'current'
  window_start: string
  window_end: string
  sample_count: number
  labelled_count: number
  schema_violation_count: number
  created_at: string
}

export interface CoverageItem {
  model_record_id: string
  name: string
  version: string
  lifecycle_state: string
  coverage: 'no_monitoring' | 'stale' | 'current'
  latest_current_snapshot_id: string | null
  latest_current_window_end: string | null
  age_days: number | null
  has_reference: boolean
  latest_sample_count: number | null
}
export interface Coverage { models: CoverageItem[]; models_total: number; models_with_current_monitoring: number; freshness_days: number }

export interface DriftFeature {
  feature: string
  type: string
  psi?: number | null
  level: string
  reason?: string
  missing_rate_reference?: number
  missing_rate_current?: number
}
export interface DriftReport {
  snapshot_id: string
  window: { start: string; end: string }
  freshness: { age_days: number; stale: boolean; stale_after_days: number }
  sample_counts: { current: number; reference: number | null; current_labelled: number; reference_labelled: number | null }
  thresholds: { psi_warn: number; psi_alert: number; min_samples: number; min_labelled: number }
  interpretation: string[]
  data_drift: { status: string; reason: string | null; features: DriftFeature[]; schema_violations: { current_rate: number; reference_rate: number | null; elevated: boolean } }
  prediction_drift: { status: string; reason: string | null; label_psi?: number | null; confidence_psi?: number | null }
  performance: {
    status: string
    reason?: string
    metric?: string
    reference?: { value: number; n: number; ci95: [number, number] }
    current?: { value: number; n: number; ci95: [number, number] }
    note?: string
  }
  operational: { status: string; reason?: string; finished_jobs?: number; failure_rate?: number | null; failure_rate_reason?: string | null; duration_seconds?: { p50: number | null; p95: number | null; sample: number } | null }
}

export interface DailyCount { date: string; counts: Record<string, number>; total: number }
export interface ObservabilitySummary {
  window_days: number
  requests: Record<string, unknown>
  inference_jobs: { daily: DailyCount[]; total: number; failure_rate: number | null; failure_rate_note: string | null }
  experiment_runs: { daily: DailyCount[]; total: number }
  review_signals: SignalPage['counts']
  unavailable: Record<string, string>
}

export interface ClassificationSampleInput { true_label: string; predicted_label: string; positive_probability?: number }
export interface ExperimentCreateBody {
  model_record_id: string
  experiment_name: string
  purpose?: string
  idempotency_key?: string
  detection?: { sample_count: number; iou_match_threshold?: number }
  classification?: { dataset_name: string; dataset_version: string; is_synthetic: boolean; positive_label?: string; labels?: string[]; samples: ClassificationSampleInput[] }
}
