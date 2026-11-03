import { request, requestText } from './client'
import type {
  Comparison, Page, ParamValues, RunDetail, RunKind, RunStatus, RunSummary, Scenario, ScenarioStatus, SimulatorsResponse,
  SweepEntryInput, TemplateDoc, ValidateResult,
} from '../types/scenario'

const json = (body: unknown) => JSON.stringify(body)

/** Phase 13 scenario simulation API. Every call goes to the real backend; all results are simulated. */
export const scenarioApi = {
  simulators: () => request<SimulatorsResponse>('/simulation/simulators'),
  templates: () => request<{ templates: TemplateDoc[] }>('/simulation/templates'),
  validate: (simulator_id: string, params: ParamValues, execution_config: { max_seconds?: number } = {}) =>
    request<ValidateResult>('/scenarios/validate', { method: 'POST', body: json({ simulator_id, params, execution_config }) }),
  list: (p: { page?: number; status?: ScenarioStatus | ''; q?: string; latestOnly?: boolean } = {}) => {
    const s = new URLSearchParams({ page: String(p.page ?? 1), page_size: '20' })
    if (p.status) s.set('status', p.status)
    if (p.q) s.set('q', p.q)
    if (p.latestOnly) s.set('latest_only', 'true')
    return request<Page<Scenario>>(`/scenarios?${s.toString()}`)
  },
  get: (id: string) => request<Scenario>(`/scenarios/${id}`),
  create: (body: Record<string, unknown>) => request<Scenario>('/scenarios', { method: 'POST', body: json(body) }),
  update: (id: string, body: Record<string, unknown>) => request<Scenario>(`/scenarios/${id}`, { method: 'PATCH', body: json(body) }),
  markReady: (id: string) => request<Scenario>(`/scenarios/${id}/ready`, { method: 'POST' }),
  duplicate: (id: string, body: Record<string, unknown> = {}) => request<Scenario>(`/scenarios/${id}/duplicate`, { method: 'POST', body: json(body) }),
  archive: (id: string) => request<Scenario>(`/scenarios/${id}/archive`, { method: 'POST' }),
  versions: (id: string) => request<Scenario[]>(`/scenarios/${id}/versions`),
  runs: (id: string, p: { page?: number; status?: RunStatus | ''; kind?: RunKind | '' } = {}) => {
    const s = new URLSearchParams({ page: String(p.page ?? 1), page_size: '20' })
    if (p.status) s.set('status', p.status)
    if (p.kind) s.set('kind', p.kind)
    return request<Page<RunSummary>>(`/scenarios/${id}/runs?${s.toString()}`)
  },
  run: (id: string, seed?: number) =>
    request<RunDetail>(`/scenarios/${id}/runs`, { method: 'POST', body: json(seed === undefined ? {} : { seed }), headers: { 'Idempotency-Key': crypto.randomUUID() } }),
  sensitivity: (id: string, body: { sweep: SweepEntryInput[]; repetitions: number; metric: string }) =>
    request<RunDetail>(`/scenarios/${id}/sensitivity`, { method: 'POST', body: json(body), headers: { 'Idempotency-Key': crypto.randomUUID() } }),
  runDetail: (runId: string) => request<RunDetail>(`/scenario-runs/${runId}`),
  retry: (runId: string) => request<RunDetail>(`/scenario-runs/${runId}/retry`, { method: 'POST' }),
  compare: (baseline_run_id: string, alternative_run_ids: string[]) =>
    request<Comparison>('/scenario-comparisons', { method: 'POST', body: json({ baseline_run_id, alternative_run_ids }) }),
  exportText: (id: string, format: 'json' | 'markdown') => requestText(`/scenarios/${id}/export?format=${format}`),
}
