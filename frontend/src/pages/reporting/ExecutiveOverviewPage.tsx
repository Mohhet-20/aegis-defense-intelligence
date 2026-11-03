import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { reportingApi } from '../../api/reporting'
import type { ExecutiveDashboard } from '../../types/reporting'
import { FilterBar } from '../../components/reporting/FilterBar'
import { useReportingFilters } from '../../components/reporting/useFilters'
import { useMetricCatalog } from '../../components/reporting/catalog'
import { BarSeries } from '../../components/reporting/Charts'
import { fmtMetric, fmtTime, fmtWindow, humanize } from '../../components/reporting/format'
import { Card, ErrorState, PageHeader, Spinner } from '../../components/ui/Primitives'

const SECTION_LINK: Record<string, string> = { events: '/reporting/analyst?section=events', observations: '/reporting/analyst?section=observations', ingestion: '/reporting/operations', sensors: '/reporting/operations', fusion: '/reporting/analyst?section=fusion', investigations: '/reporting/analyst?section=investigations', evidence: '/reporting/analyst?section=evidence', models: '/reporting/operations', review_backlog: '/reporting/analyst' }

export function ExecutiveOverviewPage() {
  const [filters, setFilters] = useReportingFilters()
  const defs = useMetricCatalog()
  const location = useLocation()
  const [data, setData] = useState<ExecutiveDashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const key = JSON.stringify(filters)
  useEffect(() => {
    let live = true
    setLoading(true); setError(null)
    reportingApi.executive(filters).then((d) => live && setData(d)).catch((e) => live && setError(e.message)).finally(() => live && setLoading(false))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  const partial = data ? Object.entries(data.section_status).filter(([, s]) => s === 'partial').map(([k]) => humanize(k)) : []
  const denied = data ? Object.entries(data.section_status).filter(([, s]) => s === 'not_authorized').map(([k]) => humanize(k)) : []
  const stale = data ? Object.values(data.sections).filter((s) => s.freshness?.stale).map((s) => humanize(s.section)) : []
  const activity = data?.sections.events?.tables.events_by_bucket
  return (
    <div>
      <PageHeader title="Executive overview" description="Counts and rates over stored records for one window. No composite or threat score is produced; every figure links to its definition and its source section." />
      <FilterBar filters={filters} onChange={setFilters} />
      {loading && <Spinner />}
      {error && <ErrorState message={error} />}
      {data && (
        <div aria-busy={loading}>
          <p className="mb-3 text-xs text-slate-500">Window {fmtWindow(data.window)} · {data.window.time_basis} time · generated {fmtTime(data.generated_at)} · definitions v{data.definition_version}</p>
          {partial.length > 0 && <p role="status" className="mb-2 rounded-md border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-sm text-status-warning">Partial data in: {partial.join(', ')}. See each section for what is omitted.</p>}
          {stale.length > 0 && <p role="status" className="mb-2 rounded-md border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-sm text-status-warning">Possibly stale: newest records in {stale.join(', ')} are older than the freshness threshold, so recent figures may be incomplete.</p>}
          {denied.length > 0 && <p role="status" className="mb-2 rounded-md border border-charcoal-600 px-3 py-2 text-sm text-slate-400">Not shown (no permission): {denied.join(', ')}.</p>}
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Key figures">
            {data.kpis.map((k) => {
              const unavailable = k.value === null
              return (
                <li key={k.metric_id} className="rounded-lg border border-charcoal-600/60 bg-charcoal-800/60 p-3">
                  <div className="text-xs text-slate-400"><abbr title={defs[k.metric_id]?.definition ?? k.metric_id} className="cursor-help no-underline decoration-dotted hover:underline">{k.label}</abbr></div>
                  {unavailable
                    ? <><div className="mt-1 text-lg text-slate-500">Not available</div><div className="text-[11px] text-slate-500">{k.reason ? humanize(k.reason) : 'no data'}</div></>
                    : <div className="mt-1 text-2xl tabular-nums text-slate-100">{fmtMetric({ value: k.value, unit: k.unit, n: k.n, reason: k.reason })}</div>}
                  <div className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
                    <span>{k.n !== null ? `n = ${k.n.toLocaleString()}` : ' '}</span>
                    <Link to={SECTION_LINK[k.section] ?? '/reporting/analyst'} className="text-accent-400 hover:underline">details</Link>
                  </div>
                </li>
              )
            })}
          </ul>
          <Card className="mt-4">
            {activity ? <BarSeries title="Events per interval" unit="events" windowText={fmtWindow(data.window)} rows={activity.rows.map((r) => [String(r[0]), Number(r[1])])} /> : <p className="text-sm text-slate-500">Event activity is not shown for your role.</p>}
            <p className="mt-2 text-xs text-slate-500">Volume changes are prompts for review, not evidence of malicious activity.</p>
          </Card>
          {data.sections.review_backlog?.tables.review_backlog && (
            <Card className="mt-4">
              <h4 className="mb-2 text-sm font-semibold text-slate-100">Awaiting human review (current)</h4>
              <ul className="space-y-1 text-sm">
                {data.sections.review_backlog.tables.review_backlog.rows.map((r) => (
                  <li key={String(r[0])} className="flex justify-between"><Link to={String(r[2])} className="text-accent-400 hover:underline">{String(r[0])}</Link><span className="tabular-nums text-slate-200">{String(r[1])}</span></li>
                ))}
              </ul>
              {data.sections.review_backlog.caveats.map((c) => <p key={c} className="mt-1 text-xs text-slate-500">{c}</p>)}
            </Card>
          )}
          <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-slate-500">{data.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
          <p className="mt-3 text-sm"><Link to={{ pathname: '/reporting/reports', search: location.search }} className="text-accent-400 hover:underline">Generate a report from these filters →</Link></p>
        </div>
      )}
    </div>
  )
}
