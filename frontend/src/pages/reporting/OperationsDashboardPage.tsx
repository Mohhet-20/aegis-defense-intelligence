import { FilterBar } from '../../components/reporting/FilterBar'
import { SectionPanel } from '../../components/reporting/SectionPanel'
import { useReportingFilters } from '../../components/reporting/useFilters'
import { useSection } from '../../components/reporting/useSection'
import { ErrorState, PageHeader, Spinner } from '../../components/ui/Primitives'
import type { Filters } from '../../types/reporting'

function Part({ name, title, filters }: { name: string; title: string; filters: Filters }) {
  const { data, error, loading } = useSection(name, filters)
  return (
    <section aria-label={title} className="mb-4">
      {loading && <Spinner />}
      {error && <ErrorState message={`${title}: ${error}`} />}
      {data && <SectionPanel env={data} title={title} />}
    </section>
  )
}

export function OperationsDashboardPage() {
  const [filters, setFilters] = useReportingFilters()
  return (
    <div>
      <PageHeader title="Operations dashboard" description="Ingestion health, sensor data coverage, background jobs, dependency readiness and model monitoring. Coverage is stored-data coverage, not uptime; AEGIS records no uptime or queue-depth telemetry." />
      <FilterBar filters={filters} onChange={setFilters} showCategory={false} />
      <Part name="ingestion" title="Ingestion and data quality" filters={filters} />
      <Part name="sensors" title="Sensor coverage and anomalies" filters={filters} />
      <Part name="system" title="System and background jobs" filters={filters} />
      <Part name="models" title="Model evaluation and monitoring" filters={filters} />
    </div>
  )
}
