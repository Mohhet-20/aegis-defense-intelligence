import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { Page, SyncConflict } from '../../types/api'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import { EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../../components/ui/Primitives'

function formatDateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '--'
}

export function EdgeConflictReviewPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [resolutionStatus, setResolutionStatus] = useState('')
  const [deviceId, setDeviceId] = useState('')
  const [recordType, setRecordType] = useState('')
  const [data, setData] = useState<Page<SyncConflict> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.edgeConflicts
      .list({ page, page_size: 20, resolution_status: resolutionStatus || undefined, device_id: deviceId || undefined, record_type: recordType || undefined })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load conflicts.'))
  }, [page, resolutionStatus, deviceId, recordType])

  return (
    <div>
      <PageHeader
        title="Conflict Review"
        description="Sync records whose local (edge) and central revisions diverged -- never resolved by unconditional last-write-wins. Compare both versions and choose keep_central, keep_local, or a manual merge."
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Field label="Resolution status">
          <select className={inputClass} value={resolutionStatus} onChange={(e) => { setPage(1); setResolutionStatus(e.target.value) }}>
            <option value="">All</option>
            <option value="unresolved">Unresolved</option>
            <option value="resolved">Resolved</option>
          </select>
        </Field>
        <Field label="Device ID">
          <input className={inputClass} value={deviceId} onChange={(e) => { setPage(1); setDeviceId(e.target.value) }} placeholder="Filter by device ID" />
        </Field>
        <Field label="Record type">
          <input className={inputClass} value={recordType} onChange={(e) => { setPage(1); setRecordType(e.target.value) }} placeholder="e.g. annotation" />
        </Field>
      </div>

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No conflicts match these filters." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            onRowClick={(row) => navigate(`/edge/conflicts/${row.id}`)}
            columns={[
              { header: 'Device', render: (c) => <span className="font-mono text-xs">{c.device_id.slice(0, 8)}</span> },
              { header: 'Record type', render: (c) => c.record_type },
              { header: 'Client record ID', render: (c) => <span className="font-mono text-xs">{c.client_record_id.slice(0, 12)}</span> },
              { header: 'Reason', render: (c) => c.conflict_reason },
              { header: 'Status', render: (c) => <StatusPill status={c.resolution_status} /> },
              { header: 'Strategy', render: (c) => (c.resolution_strategy ? c.resolution_strategy.replace(/_/g, ' ') : '--') },
              { header: 'Created', render: (c) => formatDateTime(c.created_at) },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
