import { useSearchParams } from 'react-router-dom'
import { FilterBar } from '../../components/reporting/FilterBar'
import { SectionPanel } from '../../components/reporting/SectionPanel'
import { useReportingFilters } from '../../components/reporting/useFilters'
import { useSection } from '../../components/reporting/useSection'
import { ErrorState, PageHeader, Spinner } from '../../components/ui/Primitives'
import { humanize } from '../../components/reporting/format'

const TABS = ['events', 'observations', 'ingestion', 'fusion', 'sensors', 'investigations', 'evidence', 'geo', 'review_backlog'] as const

export function AnalystWorkspacePage() {
  const [sp, setSp] = useSearchParams()
  const [filters, setFilters] = useReportingFilters()
  const section = (TABS as readonly string[]).includes(sp.get('section') ?? '') ? (sp.get('section') as string) : 'events'
  const { data, error, loading } = useSection(section, filters)
  const pick = (metricId: string, value: string) => {
    if (metricId === 'events.by_category') setFilters({ category: value }) // real drill-down: re-query this section filtered to that category
  }
  return (
    <div>
      <PageHeader title="Analyst workspace" description="Explore one section at a time. Click a category to narrow every figure to it; filters and window are kept in the address so you can share or return to this view." />
      <div role="tablist" aria-label="Analytics sections" className="mb-3 flex flex-wrap gap-1">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={t === section} type="button" onClick={() => { const s = new URLSearchParams(sp); s.set('section', t); setSp(s) }}
            className={`rounded-md px-3 py-1.5 text-sm ${t === section ? 'bg-accent-500 text-white' : 'bg-charcoal-800 text-slate-300 hover:bg-charcoal-700'}`}>{humanize(t)}</button>
        ))}
      </div>
      <FilterBar filters={filters} onChange={setFilters} showCategory={section === 'events' || section === 'observations' || section === 'geo'} />
      {loading && <Spinner />}
      {error && <ErrorState message={error} />}
      {data && <SectionPanel env={data} title={humanize(section)} onPick={pick} />}
      {filters.category && <p className="mt-2 text-xs text-slate-500">Filtered to category “{filters.category}”. <button type="button" className="text-accent-400 underline" onClick={() => setFilters({ category: '' })}>Clear</button></p>}
    </div>
  )
}
