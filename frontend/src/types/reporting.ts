export interface WindowInfo { start: string; end: string; bucket: string; time_basis: string; timezone: string; interval: string; days: number }
export interface MetricValue { value: number | string | null; unit: string; n: number | null; reason: string | null }
export interface AnalyticsTable { title: string; unit: string; columns: string[]; rows: (string | number | boolean | null)[][]; metric_ids: string[] }
export type SectionStatus = 'ok' | 'partial' | 'empty' | 'not_authorized'
export interface Freshness { age_hours?: number | null; stale?: boolean | null; stale_after_hours?: number; note?: string; [k: string]: unknown }
export interface SectionEnvelope {
  section: string; status: SectionStatus; definition_version: string; generated_at: string; window: WindowInfo
  filters: { source_id: string | null; category: string | null; include_archived: boolean }
  sample_counts: Record<string, number>; freshness: Freshness; values: Record<string, MetricValue>; tables: Record<string, AnalyticsTable>
  caveats: string[]; drilldown: Record<string, string>
}
export interface Kpi { metric_id: string; label: string; section: string; unit: string; value: number | string | null; n: number | null; reason: string | null; section_status: SectionStatus; stale: boolean | null }
export interface ExecutiveDashboard {
  generated_at: string; definition_version: string; window: WindowInfo; filters: SectionEnvelope['filters']; kpis: Kpi[]
  section_status: Record<string, SectionStatus>; sections: Record<string, SectionEnvelope>; caveats: string[]
}
export interface MetricDef { id: string; section: string; label: string; definition: string; unit: string; kind: string; time_basis: string; caveat: string | null }
export interface MetricCatalog { definition_version: string; sections: string[]; metrics: MetricDef[] }
export interface ReportTemplate { key: string; title: string; description: string; sections: string[]; custom_sections: boolean; required_permissions: string[]; available: boolean; formats: string[] }
export interface TemplateList { templates: ReportTemplate[]; formats: string[]; unsupported_formats: string[]; retention_days: number; max_artifact_bytes: number }
export interface ReportRunInfo {
  id: string; template_key: string; title: string; status: 'running' | 'completed' | 'failed' | 'expired'; format: string; visibility: string; parameters: Record<string, unknown>
  has_commentary: boolean; required_permissions: string[]; definition_version: string; created_at: string; started_at: string; completed_at: string | null; expires_at: string | null
  sample_summary: Record<string, Record<string, number>>; section_status: Record<string, string>; artifact_name: string | null; artifact_bytes: number | null
  content_sha256: string | null; integrity_note: string; download_count: number; error_category: string | null; error_message: string | null; replayed: boolean; downloadable: boolean
}
export interface ReportPage { items: ReportRunInfo[]; total: number; page: number; page_size: number }
export interface Filters { days: number; time_basis: 'event' | 'ingestion'; source_id: string; category: string; include_archived: boolean; bucket: 'auto' | 'hour' | 'day'; start?: string; end?: string }
export interface ReportBody {
  template_key: string; title?: string; format: string; sections?: string[]; days?: number; start?: string; end?: string; bucket: string; time_basis: string
  source_id?: string; category?: string; include_archived: boolean; notes?: string; visibility: string; idempotency_key?: string
}
