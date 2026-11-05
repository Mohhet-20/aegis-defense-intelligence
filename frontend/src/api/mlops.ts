import { request } from './client'
import type { Page } from '../types/api'
import type {
  ArtifactBrief, Comparison, Coverage, DriftReport, ExperimentCreateBody, ExperimentRun, LifecycleEvent, MetricHistory, ModelFamily,
  ModelVersion, MonitoringSnapshot, ObservabilitySummary, ReviewSignal, SignalPage, TransitionAction,
} from '../types/mlops'

const json = (body: unknown) => JSON.stringify(body)
const qs = (params: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') s.set(k, String(v)) })
  const out = s.toString()
  return out ? `?${out}` : ''
}

/** The MLOps layer MLOps API. Every call hits a real backend route; permissions are enforced server-side. */
export const mlopsApi = {
  families: (q = '', page = 1) => request<Page<ModelFamily>>(`/mlops/families${qs({ q, page, page_size: 50 })}`),
  versions: (f: { q?: string; task?: string; lifecycle_state?: string; family?: string }, page = 1, pageSize = 25) =>
    request<Page<ModelVersion>>(`/mlops/models${qs({ ...f, page, page_size: pageSize })}`),
  version: (id: string) => request<ModelVersion>(`/mlops/models/${id}`),
  history: (id: string) => request<{ items: LifecycleEvent[] }>(`/mlops/models/${id}/history`),
  transition: (id: string, action: TransitionAction, reason: string) =>
    request<ModelVersion>(`/mlops/models/${id}/transition`, { method: 'POST', body: json({ action, reason }) }),
  verifyArtifact: (id: string) => request<ArtifactBrief & { review_signal_id: string | null }>(`/mlops/models/${id}/verify-artifact`, { method: 'POST' }),
  registerVersion: (body: Record<string, unknown>) => request<ModelVersion>('/mlops/models', { method: 'POST', body: json(body) }),

  experiments: (f: { model_record_id?: string; task?: string; status?: string }, page = 1, pageSize = 25) =>
    request<Page<ExperimentRun>>(`/mlops/experiments${qs({ ...f, page, page_size: pageSize })}`),
  experiment: (id: string) => request<ExperimentRun>(`/mlops/experiments/${id}`),
  createExperiment: (body: ExperimentCreateBody) => request<ExperimentRun>('/mlops/experiments', { method: 'POST', body: json(body) }),
  comparison: (id: string, baselineRunId?: string) => request<Comparison>(`/mlops/experiments/${id}/comparison${qs({ baseline_run_id: baselineRunId })}`),
  metricHistory: (p: { metric: string; task: string; model_record_id?: string; days?: number }) =>
    request<MetricHistory>(`/mlops/experiments/history${qs({ ...p, days: p.days ?? 90 })}`),
  baselines: () => request<{ items: { id: string; task: string; dataset_name: string; dataset_version: string; run_id: string; selected_at: string; reason: string | null }[] }>('/mlops/baselines'),
  selectBaseline: (run_id: string, reason?: string) => request<unknown>('/mlops/baselines', { method: 'PUT', body: json({ run_id, reason }) }),

  snapshots: (model_record_id?: string, page = 1) => request<Page<MonitoringSnapshot>>(`/mlops/monitoring/snapshots${qs({ model_record_id, page, page_size: 25 })}`),
  drift: (snapshotId: string) => request<DriftReport>(`/mlops/monitoring/snapshots/${snapshotId}/drift`),
  coverage: () => request<Coverage>('/mlops/monitoring/coverage'),

  signals: (f: { status?: string; severity?: string; category?: string; model_record_id?: string }, page = 1, pageSize = 25) =>
    request<SignalPage>(`/mlops/signals${qs({ ...f, page, page_size: pageSize })}`),
  acknowledge: (id: string, assignee_user_id?: string) =>
    request<ReviewSignal>(`/mlops/signals/${id}/acknowledge`, { method: 'POST', body: json(assignee_user_id ? { assignee_user_id } : {}) }),
  resolve: (id: string, notes: string) => request<ReviewSignal>(`/mlops/signals/${id}/resolve`, { method: 'POST', body: json({ notes }) }),
  scan: () => request<Record<string, unknown>>('/mlops/signals/scan', { method: 'POST' }),

  summary: (days = 7) => request<ObservabilitySummary>(`/observability/summary?days=${days}`),
}
