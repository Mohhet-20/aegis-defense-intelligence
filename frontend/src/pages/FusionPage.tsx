import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { FusionJob } from '../types/api'
import { Button, Card, ErrorState, PageHeader, Spinner, StatTile, StatusPill } from '../components/ui/Primitives'

interface Counts {
  candidateRelationships: number
  unresolvedConflicts: number
  assessmentsInProgress: number
  evidenceItems: number
}

export function FusionPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [counts, setCounts] = useState<Counts | null>(null)
  const [recentJobs, setRecentJobs] = useState<FusionJob[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [runMessage, setRunMessage] = useState<string | null>(null)

  const canRun = user?.role === 'administrator' || user?.role === 'analyst'

  function load() {
    Promise.all([
      api.relationships.list({ review_status: 'candidate', page_size: 1 }),
      api.conflicts.list({ review_status: 'unresolved', page_size: 1 }),
      api.assessments.list({ status: 'in_review', page_size: 1 }),
      api.evidence.list({ page_size: 1 }),
      api.fusion.jobs(1, 5),
    ])
      .then(([relationships, conflicts, assessments, evidence, jobs]) => {
        setCounts({
          candidateRelationships: relationships.total,
          unresolvedConflicts: conflicts.total,
          assessmentsInProgress: assessments.total,
          evidenceItems: evidence.total,
        })
        setRecentJobs(jobs.items)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [])

  async function handleRun() {
    setRunning(true)
    setRunMessage(null)
    try {
      const job = await api.fusion.run({})
      setRunMessage(
        job.status === 'completed'
          ? `Fusion job completed -- considered ${job.events_considered} events, created ${job.correlations_created} correlation(s) and ${job.conflicts_created} conflict(s) (rule v${job.rule_version}).`
          : `Fusion job ${job.status}${job.error_message ? `: ${job.error_message}` : ''}`,
      )
      load()
    } catch (err) {
      setRunMessage(err instanceof ApiError ? err.message : 'Fusion run failed.')
    } finally {
      setRunning(false)
    }
  }

  if (error) return <ErrorState message={error} />
  if (!counts) return <Spinner />

  return (
    <div>
      <PageHeader
        title="Intelligence Fusion"
        description="Composes correlation recompute and conflict detection into one auditable run. Running fusion never auto-confirms a relationship or auto-resolves a conflict -- every candidate still needs a human review."
        actions={
          canRun && (
            <Button onClick={handleRun} disabled={running}>
              {running ? 'Running…' : 'Run fusion now'}
            </Button>
          )
        }
      />

      {runMessage && <div className="mb-4 text-sm text-slate-300">{runMessage}</div>}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatTile
          label="Relationships awaiting review"
          value={counts.candidateRelationships}
          hint="candidate review_status"
        />
        <StatTile label="Unresolved conflicts" value={counts.unresolvedConflicts} />
        <StatTile label="Assessments in review" value={counts.assessmentsInProgress} />
        <StatTile label="Evidence items" value={counts.evidenceItems} />
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Workspaces</h2>
          <div className="flex flex-col gap-2">
            <Button variant="secondary" onClick={() => navigate('/fusion/relationships')}>
              Relationship review
            </Button>
            <Button variant="secondary" onClick={() => navigate('/fusion/conflicts')}>
              Conflict review center
            </Button>
            <Button variant="secondary" onClick={() => navigate('/fusion/evidence')}>
              Evidence library
            </Button>
            <Button variant="secondary" onClick={() => navigate('/fusion/assessments')}>
              Assessment workspace
            </Button>
            <Button variant="secondary" onClick={() => navigate('/fusion/graph')}>
              Evidence graph explorer
            </Button>
          </div>
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Recent fusion jobs</h2>
          {recentJobs && recentJobs.length === 0 && <p className="text-sm text-slate-500">No fusion job has run yet.</p>}
          {recentJobs && recentJobs.length > 0 && (
            <ul className="space-y-2">
              {recentJobs.map((job) => (
                <li key={job.id} className="flex items-center justify-between border-b border-charcoal-700/50 py-2 text-sm last:border-0">
                  <div>
                    <div className="text-slate-300">{new Date(job.started_at).toLocaleString()}</div>
                    <div className="text-xs text-slate-500">
                      {job.events_considered} events · {job.correlations_created} correlations · {job.conflicts_created} conflicts
                    </div>
                  </div>
                  <StatusPill status={job.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card className="mt-6">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">What this does NOT do</h2>
        <p className="text-sm text-slate-400">
          Fusion never merges or auto-resolves anything. A relationship it creates stays a &quot;candidate&quot; until an
          analyst confirms, rejects, or marks it uncertain. A conflict it detects stays &quot;unresolved&quot; until an
          analyst records a resolution and a rationale. Conflict detection is scoped to event pairs that already have a
          Correlation -- it is never an independent all-pairs scan of the whole dataset.
        </p>
      </Card>
    </div>
  )
}
