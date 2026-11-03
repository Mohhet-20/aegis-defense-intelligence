import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type { Page, SyncRecord, SyncQueueSummary } from '../../types/api'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import {
  Button,
  EmptyState,
  ErrorState,
  Field,
  PageHeader,
  Spinner,
  StatTile,
  StatusPill,
  inputClass,
} from '../../components/ui/Primitives'

const RETRYABLE_STATUSES = new Set(['retryable_failure', 'permanent_failure'])
const CANCELLABLE_STATUSES = new Set(['queued', 'retryable_failure'])

function formatDateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '--'
}

function formatAge(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return 'not available'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

function SummaryStrip({ summary }: { summary: SyncQueueSummary }) {
  const byStatus = Object.fromEntries(summary.by_status.map((s) => [s.sync_status, s.count]))
  return (
    <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
      <StatTile label="Total records" value={summary.total_records} />
      <StatTile label="Oldest pending age" value={formatAge(summary.oldest_pending_age_seconds)} />
      <StatTile label="Unresolved conflicts" value={summary.unresolved_conflict_count} />
      <StatTile label="Quarantined" value={summary.quarantined_count} />
      <StatTile label="Devices with pending records" value={summary.devices_with_pending_records} />
      {Object.entries(byStatus).map(([status, count]) => (
        <StatTile key={status} label={status.replace(/_/g, ' ')} value={count} />
      ))}
    </div>
  )
}

export function EdgeSyncQueuePage() {
  const { user } = useAuth()
  const [summary, setSummary] = useState<SyncQueueSummary | null>(null)
  const [summaryError, setSummaryError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [deviceId, setDeviceId] = useState('')
  const [syncStatus, setSyncStatus] = useState('')
  const [recordType, setRecordType] = useState('')
  const [data, setData] = useState<Page<SyncRecord> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actingOn, setActingOn] = useState<string | null>(null)
  const [recovering, setRecovering] = useState(false)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst'

  function loadSummary() {
    api.edgeSync
      .queueSummary()
      .then((s) => {
        setSummary(s)
        setSummaryError(null)
      })
      .catch((e) => setSummaryError(e instanceof ApiError ? e.message : 'Failed to load queue summary.'))
  }

  function loadRecords() {
    api.edgeSync
      .records({ page, page_size: 20, device_id: deviceId || undefined, sync_status: syncStatus || undefined, record_type: recordType || undefined })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load sync records.'))
  }

  useEffect(loadSummary, [])
  useEffect(() => {
    loadRecords()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, deviceId, syncStatus, recordType])

  async function handleRetry(record: SyncRecord) {
    setActingOn(record.id)
    setActionError(null)
    try {
      await api.edgeSync.retry(record.id)
      loadRecords()
      loadSummary()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Retry failed.')
    } finally {
      setActingOn(null)
    }
  }

  async function handleCancel(record: SyncRecord) {
    setActingOn(record.id)
    setActionError(null)
    try {
      await api.edgeSync.cancel(record.id)
      loadRecords()
      loadSummary()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Cancel failed.')
    } finally {
      setActingOn(null)
    }
  }

  async function handleRecoverStale() {
    setRecovering(true)
    setActionError(null)
    try {
      const result = await api.edgeSync.recoverStale()
      setActionError(null)
      loadRecords()
      loadSummary()
      window.alert(`Recovered ${result.recovered_count} stale syncing record(s).`)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Recovery sweep failed.')
    } finally {
      setRecovering(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Sync Queue"
        description="Org-wide view of every SyncRecord submitted by edge devices -- durable local queue entries that have reached the central server. There is no background scheduler in this build; recovery of crashed in-flight records is a manual sweep below."
        actions={
          canManage && (
            <Button variant="secondary" onClick={handleRecoverStale} disabled={recovering}>
              {recovering ? 'Recovering…' : 'Recover stale syncing records'}
            </Button>
          )
        }
      />

      {summaryError && <ErrorState message={summaryError} />}
      {!summary && !summaryError && <Spinner />}
      {summary && <SummaryStrip summary={summary} />}

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Field label="Device ID">
          <input className={inputClass} value={deviceId} onChange={(e) => { setPage(1); setDeviceId(e.target.value) }} placeholder="Filter by device ID" />
        </Field>
        <Field label="Sync status">
          <select className={inputClass} value={syncStatus} onChange={(e) => { setPage(1); setSyncStatus(e.target.value) }}>
            <option value="">All</option>
            <option value="queued">Queued</option>
            <option value="syncing">Syncing</option>
            <option value="synced">Synced</option>
            <option value="retryable_failure">Retryable failure</option>
            <option value="permanent_failure">Permanent failure</option>
            <option value="conflict">Conflict</option>
            <option value="quarantined">Quarantined</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </Field>
        <Field label="Record type">
          <input className={inputClass} value={recordType} onChange={(e) => { setPage(1); setRecordType(e.target.value) }} placeholder="e.g. annotation" />
        </Field>
      </div>

      {actionError && <div className="mb-3"><ErrorState message={actionError} /></div>}

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No sync records match these filters." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            columns={[
              { header: 'Device', render: (r) => <span className="font-mono text-xs">{r.device_id.slice(0, 8)}</span> },
              { header: 'Record type', render: (r) => r.record_type },
              { header: 'Status', render: (r) => <StatusPill status={r.sync_status} /> },
              { header: 'Retries', render: (r) => r.retry_count },
              { header: 'Queued', render: (r) => formatDateTime(r.queued_at) },
              { header: 'Next retry', render: (r) => formatDateTime(r.next_retry_at) },
              { header: 'Last error', render: (r) => r.last_error_message ?? '--' },
              ...(canManage
                ? [
                    {
                      header: 'Actions',
                      render: (r: SyncRecord) => (
                        <div className="flex gap-2">
                          <Button
                            variant="secondary"
                            disabled={!RETRYABLE_STATUSES.has(r.sync_status) || actingOn === r.id}
                            onClick={() => handleRetry(r)}
                          >
                            Retry
                          </Button>
                          <Button
                            variant="danger"
                            disabled={!CANCELLABLE_STATUSES.has(r.sync_status) || actingOn === r.id}
                            onClick={() => handleCancel(r)}
                          >
                            Cancel
                          </Button>
                        </div>
                      ),
                    },
                  ]
                : []),
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
