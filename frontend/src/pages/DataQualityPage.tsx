import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DataQualitySummary, DataSource, JobsSummary } from '../types/api'
import { Card, ErrorState, Field, PageHeader, Spinner, StatTile, inputClass } from '../components/ui/Primitives'

function Percent({ value }: { value: number | null }) {
  if (value === null) return <span className="text-slate-500">n/a (no records yet)</span>
  return <span>{(value * 100).toFixed(1)}%</span>
}

function CategoryList({ categories }: { categories: Record<string, number> }) {
  const entries = Object.entries(categories).sort((a, b) => b[1] - a[1])
  if (entries.length === 0) return <p className="text-sm text-slate-500">None.</p>
  return (
    <ul className="space-y-1 text-sm">
      {entries.map(([code, count]) => (
        <li key={code} className="flex justify-between border-b border-charcoal-700/50 py-1 last:border-0">
          <span className="text-slate-400">{code.replace(/_/g, ' ')}</span>
          <span className="font-mono text-slate-200">{count}</span>
        </li>
      ))}
    </ul>
  )
}

export function DataQualityPage() {
  const [sources, setSources] = useState<DataSource[]>([])
  const [sourceId, setSourceId] = useState('')
  const [quality, setQuality] = useState<DataQualitySummary | null>(null)
  const [jobs, setJobs] = useState<JobsSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.sources.list().then((d) => setSources(d.items))
  }, [])

  useEffect(() => {
    const params = sourceId ? { source_id: sourceId } : {}
    Promise.all([api.dataQuality.summary(params), api.dataQuality.jobsSummary(params)])
      .then(([q, j]) => {
        setQuality(q)
        setJobs(j)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }, [sourceId])

  return (
    <div>
      <PageHeader
        title="Data Quality Dashboard"
        description="Computed on the fly from stored validation outcomes -- every rate below states its own denominator (total), never a single opaque score."
      />

      <div className="mb-5 max-w-xs">
        <Field label="Scope to one source">
          <select className={inputClass} value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
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
      {!quality && !error && <Spinner />}

      {quality && jobs && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Total raw records" value={quality.total} hint="the denominator every rate below is computed against" />
            <StatTile label="Acceptance rate" value={<Percent value={quality.acceptance_rate} />} hint={`${quality.accepted ?? 0} accepted`} />
            <StatTile label="Rejection rate" value={<Percent value={quality.rejection_rate} />} hint={`${quality.invalid} invalid`} />
            <StatTile label="Duplicate rate" value={<Percent value={quality.duplicate_rate} />} hint={`${quality.duplicate} duplicates`} />
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <Card>
              <h2 className="mb-2 text-sm font-semibold text-slate-200">Rejection categories</h2>
              <CategoryList categories={quality.rejection_categories} />
            </Card>
            <Card>
              <h2 className="mb-2 text-sm font-semibold text-slate-200">Warning categories</h2>
              <CategoryList categories={quality.warning_categories} />
            </Card>
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Total jobs" value={jobs.total_jobs} />
            <StatTile label="Jobs completed" value={jobs.by_status.completed ?? 0} />
            <StatTile label="Jobs with errors" value={jobs.by_status.completed_with_errors ?? 0} />
            <StatTile label="Jobs failed" value={jobs.by_status.failed ?? 0} />
          </div>
        </>
      )}
    </div>
  )
}
