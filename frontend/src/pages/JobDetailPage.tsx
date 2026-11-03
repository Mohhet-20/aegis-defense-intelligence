import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { IngestionJob, Page, RawRecord } from '../types/api'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { Button, Card, ErrorState, PageHeader, Spinner, StatusPill } from '../components/ui/Primitives'

const RETRYABLE_JOB_TYPES = new Set(['http_api', 'synthetic_demo', 'synthetic_generator'])

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between border-b border-charcoal-700/50 py-2 text-sm last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  )
}

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [job, setJob] = useState<IngestionJob | null>(null)
  const [records, setRecords] = useState<Page<RawRecord> | null>(null)
  const [page, setPage] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [recordsError, setRecordsError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [retryMessage, setRetryMessage] = useState<string | null>(null)

  const canRetry = user?.role === 'administrator' || user?.role === 'analyst'
  // Mirrors the backend's RAW_RECORD_READ grant; the server still enforces it.
  const canSeeRawRecords = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  function loadJob() {
    if (!jobId) return
    api.ingestion.get(jobId).then(setJob).catch((e) => setError(e.message))
  }

  useEffect(loadJob, [jobId])
  useEffect(() => {
    if (!jobId) return
    if (!canSeeRawRecords) {
      setRecordsError('Raw records are visible to analysts, investigators and administrators only.')
      return
    }
    api.ingestion
      .rawRecords(jobId, page, 20)
      .then((d) => {
        setRecords(d)
        setRecordsError(null)
      })
      .catch((e) => setRecordsError(e instanceof ApiError && e.status === 403 ? 'You do not have permission to view raw records (analyst/investigator/administrator only).' : e.message))
  }, [jobId, page, canSeeRawRecords])

  async function handleRetry() {
    if (!jobId) return
    setRetrying(true)
    setRetryMessage(null)
    try {
      const newJob = await api.ingestion.retry(jobId)
      setRetryMessage(`Retry created job ${newJob.id} -- ${newJob.status}.`)
      navigate(`/ingestion/${newJob.id}`)
    } catch (err) {
      setRetryMessage(err instanceof ApiError ? err.message : 'Retry failed.')
    } finally {
      setRetrying(false)
    }
  }

  if (error) return <ErrorState message={error} />
  if (!job) return <Spinner />

  return (
    <div>
      <PageHeader
        title={`Ingestion Job ${job.id.slice(0, 8)}`}
        description={
          <>
            <Link to="/ingestion" className="text-accent-400 hover:underline">
              Ingestion Center
            </Link>{' '}
            / job detail
          </>
        }
        actions={
          canRetry &&
          RETRYABLE_JOB_TYPES.has(job.job_type) && (
            <Button onClick={handleRetry} disabled={retrying}>
              {retrying ? 'Retrying…' : 'Retry'}
            </Button>
          )
        }
      />
      {retryMessage && <div className="mb-4 text-sm text-slate-300">{retryMessage}</div>}

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Job metadata</h2>
          <Row label="Type" value={job.job_type} />
          <Row label="Trigger" value={job.trigger_type} />
          <Row label="Status" value={<StatusPill status={job.status} />} />
          <Row label="Source" value={<span className="font-mono text-xs">{job.source_id}</span>} />
          <Row label="Started" value={new Date(job.started_at).toLocaleString()} />
          <Row label="Completed" value={job.completed_at ? new Date(job.completed_at).toLocaleString() : '--'} />
          <Row label="Retry count" value={job.retry_count} />
          {!RETRYABLE_JOB_TYPES.has(job.job_type) && (
            <p className="mt-2 text-xs text-slate-500">
              File-upload jobs cannot be auto-retried -- the original bytes are not persisted indefinitely. Re-upload the file to try again.
            </p>
          )}
        </Card>

        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Outcome counts</h2>
          <Row label="Accepted" value={job.accepted_count} />
          <Row label="Rejected" value={job.rejected_count} />
          <Row label="Skipped" value={job.skipped_count} />
          <Row label="Duplicate" value={job.duplicate_count} />
        </Card>

        {job.error_summary.length > 0 && (
          <Card className="md:col-span-2">
            <h2 className="mb-2 text-sm font-semibold text-slate-200">Error summary (bounded to 50)</h2>
            <ul className="space-y-1 text-xs text-status-critical">
              {job.error_summary.map((e, i) => (
                <li key={i}>{e.index !== undefined ? `#${e.index}: ` : ''}{e.error}</li>
              ))}
            </ul>
          </Card>
        )}

        <Card className="md:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Raw records (provenance)</h2>
          {recordsError && <ErrorState message={recordsError} />}
          {!recordsError && !records && <Spinner />}
          {records && records.items.length === 0 && <p className="text-sm text-slate-500">No raw records for this job.</p>}
          {records && records.items.length > 0 && (
            <>
              <DataTable
                rows={records.items}
                columns={[
                  { header: 'External ID', render: (r) => r.external_record_id ?? <span className="text-slate-500">(fingerprint fallback)</span> },
                  { header: 'Validation', render: (r) => <StatusPill status={r.validation_status} /> },
                  { header: 'Duplicate', render: (r) => (r.is_duplicate ? <StatusPill status="failed" /> : <span className="text-slate-500">no</span>) },
                  { header: 'Errors', render: (r) => r.validation_errors.length },
                  { header: 'Warnings', render: (r) => r.validation_warnings.length },
                  { header: 'Linked event', render: (r) => (r.event_id ? <span className="font-mono text-xs">{r.event_id.slice(0, 8)}</span> : '--') },
                ]}
              />
              <Pagination page={records.page} pageSize={records.page_size} total={records.total} onPageChange={setPage} />
            </>
          )}
        </Card>
      </div>
    </div>
  )
}
