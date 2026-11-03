import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { DataSource, IngestionJob, Page } from '../types/api'
import { useAuth } from '../context/auth'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

export function IngestionJobsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [sourceFilter, setSourceFilter] = useState('')
  const [data, setData] = useState<Page<IngestionJob> | null>(null)
  const [sources, setSources] = useState<DataSource[]>([])
  const [sourceId, setSourceId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  const canUpload = user?.role === 'administrator' || user?.role === 'analyst'

  function load() {
    api.ingestion
      .list(page, 20, sourceFilter || undefined)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [page, sourceFilter])
  useEffect(() => {
    api.sources.list().then((d) => {
      setSources(d.items)
      if (canUpload && d.items.length > 0) setSourceId(d.items[0].id)
    })
  }, [canUpload])

  async function handleUpload(e: FormEvent) {
    e.preventDefault()
    if (!file || !sourceId) return
    setUploadError(null)
    setUploading(true)
    try {
      await api.ingestion.upload(sourceId, file)
      setFile(null)
      load()
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div>
      <PageHeader title="Ingestion Center" description="JSON and CSV uploads plus connector-driven source runs, with honest partial-failure reporting -- never an all-or-nothing result." />

      {canUpload && (
        <Card className="mb-5 max-w-lg">
          <form onSubmit={handleUpload} className="space-y-3">
            <Field label="Data source">
              <select
                className="w-full rounded-md border border-charcoal-600 bg-charcoal-900 px-3 py-1.5 text-sm text-slate-200"
                value={sourceId}
                onChange={(e) => setSourceId(e.target.value)}
              >
                {sources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="File (.json or .csv)">
              <input
                type="file"
                accept=".json,.csv"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="w-full text-sm text-slate-300"
              />
            </Field>
            {uploadError && <ErrorState message={uploadError} />}
            <Button type="submit" disabled={uploading || !file || !sourceId}>
              {uploading ? 'Uploading…' : 'Upload'}
            </Button>
          </form>
        </Card>
      )}

      <div className="mb-4 max-w-xs">
        <Field label="Filter by source">
          <select className={inputClass} value={sourceFilter} onChange={(e) => { setPage(1); setSourceFilter(e.target.value) }}>
            <option value="">All sources</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No ingestion jobs have run yet." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            onRowClick={(row) => navigate(`/ingestion/${row.id}`)}
            columns={[
              { header: 'Type', render: (r) => r.job_type },
              { header: 'Trigger', render: (r) => r.trigger_type },
              { header: 'Status', render: (r) => <StatusPill status={r.status} /> },
              { header: 'Accepted', render: (r) => r.accepted_count },
              { header: 'Rejected', render: (r) => r.rejected_count },
              { header: 'Duplicate', render: (r) => r.duplicate_count },
              { header: 'Retries', render: (r) => r.retry_count },
              { header: 'Started', render: (r) => new Date(r.started_at).toLocaleString() },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
