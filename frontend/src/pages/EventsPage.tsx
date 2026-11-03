import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { AegisEvent, Page } from '../types/api'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { Button, DataOriginBadge, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

export function EventsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [searchParams] = useSearchParams() // drill-down links from the analytics dashboards pass these filters
  const [eventType, setEventType] = useState(searchParams.get('event_type') ?? '')
  const [dataOrigin, setDataOrigin] = useState(searchParams.get('data_origin') ?? '')
  const [data, setData] = useState<Page<AegisEvent> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const canExport = user?.role === 'administrator' || user?.role === 'analyst'

  useEffect(() => {
    setLoading(true)
    api.events
      .list({ page, page_size: 20, event_type: eventType || undefined, data_origin: dataOrigin || undefined })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [page, eventType, dataOrigin])

  async function handleExport() {
    setExporting(true)
    setExportError(null)
    try {
      await api.events.exportDownload({ event_type: eventType || undefined, data_origin: dataOrigin || undefined, format: 'csv' })
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : 'Export failed.')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Event Explorer"
        description="Events ingested from registered data sources."
        actions={
          canExport && (
            <Button variant="secondary" onClick={handleExport} disabled={exporting}>
              {exporting ? 'Exporting…' : 'Export CSV'}
            </Button>
          )
        }
      />
      {exportError && <div className="mb-4"><ErrorState message={exportError} /></div>}

      <div className="mb-4 flex max-w-xl gap-4">
        <Field label="Filter by event type">
          <input
            className={inputClass}
            placeholder="e.g. perimeter_motion"
            value={eventType}
            onChange={(e) => {
              setPage(1)
              setEventType(e.target.value)
            }}
          />
        </Field>
        <Field label="Data origin">
          <select
            className={inputClass}
            value={dataOrigin}
            onChange={(e) => {
              setPage(1)
              setDataOrigin(e.target.value)
            }}
          >
            <option value="">All</option>
            <option value="user_upload">user_upload</option>
            <option value="external_source">external_source</option>
            <option value="synthetic_demo">synthetic_demo</option>
          </select>
        </Field>
      </div>

      {error && <ErrorState message={error} />}
      {loading && !data && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No events match these filters." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            onRowClick={(row) => navigate(`/events/${row.id}`)}
            columns={[
              { header: 'Title', render: (r) => r.title },
              { header: 'Type', render: (r) => r.event_type },
              { header: 'Priority', render: (r) => (r.priority ? <StatusPill status={r.priority} /> : <span className="text-slate-500">--</span>) },
              { header: 'Observed', render: (r) => new Date(r.observed_at).toLocaleString() },
              { header: 'Origin', render: (r) => <DataOriginBadge origin={r.data_origin} /> },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
