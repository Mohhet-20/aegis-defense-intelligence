import { ApiError, getAccessToken, request } from './client'
import type { ExecutiveDashboard, Filters, MetricCatalog, ReportBody, ReportPage, ReportRunInfo, SectionEnvelope, TemplateList } from '../types/reporting'

const qs = (f: Partial<Filters>) => {
  const s = new URLSearchParams()
  if (f.start && f.end) { s.set('start', f.start); s.set('end', f.end) } else if (f.days) s.set('days', String(f.days))
  if (f.time_basis) s.set('time_basis', f.time_basis)
  if (f.bucket && f.bucket !== 'auto') s.set('bucket', f.bucket)
  if (f.source_id) s.set('source_id', f.source_id)
  if (f.category) s.set('category', f.category)
  if (f.include_archived) s.set('include_archived', 'true')
  const out = s.toString()
  return out ? `?${out}` : ''
}

/** Analytics/reporting API: every call hits a real route; authorization is enforced server-side. */
export const reportingApi = {
  metrics: () => request<MetricCatalog>('/reporting/metrics'),
  section: (name: string, f: Partial<Filters>) => request<SectionEnvelope>(`/reporting/analytics/${name}${qs(f)}`),
  executive: (f: Partial<Filters>) => request<ExecutiveDashboard>(`/reporting/dashboards/executive${qs(f)}`),
  templates: () => request<TemplateList>('/reporting/templates'),
  validate: (body: ReportBody) => request<Record<string, unknown>>('/reporting/reports/validate', { method: 'POST', body: JSON.stringify(body) }),
  create: (body: ReportBody) => request<ReportRunInfo>('/reporting/reports', { method: 'POST', body: JSON.stringify(body) }),
  list: (page = 1, status?: string) => request<ReportPage>(`/reporting/reports?page=${page}&page_size=20${status ? `&status=${status}` : ''}`),
  get: (id: string) => request<ReportRunInfo>(`/reporting/reports/${id}`),
  /** Authenticated download (the file has no public URL); saved via a temporary object URL. */
  async download(run: ReportRunInfo): Promise<void> {
    const token = getAccessToken()
    const res = await fetch(`/api/v1/reporting/reports/${run.id}/download`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
    if (!res.ok) {
      let detail = `Download failed (${res.status})`
      try { const b = await res.json(); if (typeof b.detail === 'string') detail = b.detail } catch { /* keep generic */ }
      throw new ApiError(res.status, detail, null)
    }
    const url = URL.createObjectURL(await res.blob())
    const a = document.createElement('a')
    a.href = url
    a.download = run.artifact_name ?? `report-${run.id}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  },
}
