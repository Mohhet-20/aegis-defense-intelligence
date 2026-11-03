import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ReadinessResponse } from '../types/api'
import { Card, ErrorState, PageHeader, Spinner, StatusPill } from '../components/ui/Primitives'

export function HealthPage() {
  const [ready, setReady] = useState<ReadinessResponse | null>(null)
  const [live, setLive] = useState<{ status: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.health.live(), api.health.ready()])
      .then(([l, r]) => {
        setLive(l)
        setReady(r)
      })
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <ErrorState message={error} />
  if (!live || !ready) return <Spinner />

  return (
    <div>
      <PageHeader title="System Health" description="Live probes against the running backend -- not a static status page." />
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Liveness</h2>
          <StatusPill status={live.status} />
          <p className="mt-2 text-xs text-slate-500">GET /api/v1/health/live -- confirms the process is up.</p>
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Readiness</h2>
          <StatusPill status={ready.status} />
          <p className="mt-1 text-xs text-slate-400">Database: <StatusPill status={ready.checks.database} /></p>
          {ready.checks.media_storage && <p className="mt-1 text-xs text-slate-400">Media storage: <StatusPill status={ready.checks.media_storage} /></p>}
          {ready.checks.model_runtime && <p className="mt-1 text-xs text-slate-400">CV model runtime: <StatusPill status={ready.checks.model_runtime} /></p>}
          <p className="mt-2 text-xs text-slate-500">GET /api/v1/health/ready -- confirms every real dependency (database, media storage, the CV model runtime) actually works, not just that the process is up.</p>
        </Card>
      </div>
    </div>
  )
}
