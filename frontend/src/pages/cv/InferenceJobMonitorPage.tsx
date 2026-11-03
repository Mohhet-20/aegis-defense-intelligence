import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { InferenceJob, Page } from '../../types/api'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import { EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../../components/ui/Primitives'

export function InferenceJobMonitorPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const [data, setData] = useState<Page<InferenceJob> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.inference
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
        title="Inference Job Monitor"
        description="Every job runs synchronously inside its own API request -- there is no background worker in this build yet. See docs/ml/INFERENCE_PIPELINE.md."
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
      {data && data.items.length === 0 && <EmptyState message="No inference jobs have run yet." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            onRowClick={(row) => navigate(`/cv/jobs/${row.id}`)}
            columns={[
              { header: 'Type', render: (r) => r.job_type },
              { header: 'Status', render: (r) => <StatusPill status={r.status} /> },
              { header: 'Frames', render: (r) => r.frames_processed },
              { header: 'Detections', render: (r) => r.detections_created },
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
