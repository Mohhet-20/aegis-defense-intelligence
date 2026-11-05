import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { Page, TrackingJob } from '../../types/api'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import { EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../../components/ui/Primitives'

export function TrackingJobMonitorPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const [data, setData] = useState<Page<TrackingJob> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.tracking
      .list({ page, page_size: 20, status: statusFilter || undefined })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }, [page, statusFilter])

  return (
    <div>
      <PageHeader
        title="Tracking Job Monitor"
        description="Every tracking job runs synchronously inside its own API request, exactly like the inference jobs -- there is still no background worker in this build. See docs/operations/TRACKING_OPERATIONS.md."
      />

      <div className="mb-4 max-w-xs">
        <Field label="Filter by status">
          <select className={inputClass} value={statusFilter} onChange={(e) => { setPage(1); setStatusFilter(e.target.value) }}>
            <option value="">All statuses</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="running">Running</option>
            <option value="pending">Pending</option>
          </select>
        </Field>
      </div>

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No tracking jobs have run yet." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            onRowClick={(row) => navigate(`/tracking/jobs/${row.id}`)}
            columns={[
              { header: 'Tracker', render: (r) => `${r.tracker_key} v${r.tracker_version}` },
              { header: 'Status', render: (r) => <StatusPill status={r.status} /> },
              { header: 'Frames', render: (r) => r.frames_processed },
              { header: 'Tracks created', render: (r) => r.tracks_created },
              { header: 'Retries', render: (r) => r.retry_count },
              { header: 'Started', render: (r) => (r.started_at ? new Date(r.started_at).toLocaleString() : '--') },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
