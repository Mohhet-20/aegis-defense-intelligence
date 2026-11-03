import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type { SpatialRelationshipCandidate } from '../../types/api'
import { Button, Card, EmptyState, ErrorState, PageHeader, Spinner, StatusPill } from '../../components/ui/Primitives'

const REVIEW_FILTERS = ['candidate', 'confirmed', 'rejected', 'uncertain', '']

export function SpatialRelationshipExplorerPage() {
  const { user } = useAuth()
  const [reviewStatus, setReviewStatus] = useState('candidate')
  const [candidates, setCandidates] = useState<SpatialRelationshipCandidate[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [runResult, setRunResult] = useState<string | null>(null)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst'
  const canReview = canManage || user?.role === 'investigator'

  function load() {
    setError(null)
    api.geospatial
      .listRelationships({ review_status: reviewStatus || undefined, limit: 200 })
      .then(setCandidates)
      .catch((e) => setError(e.message))
  }

  useEffect(load, [reviewStatus])

  async function handleGenerate() {
    setGenerating(true)
    setRunResult(null)
    try {
      const result = await api.geospatial.generateRelationships({})
      setRunResult(
        `Created ${result.candidates_created} new candidate(s), ${result.candidates_already_known} already known, over ${result.pairs_considered} pair(s) from ${result.candidates_considered} located record(s) (rule ${result.rule_version}).` +
          (result.candidates_truncated
            ? ' The per-run limit was reached: only the earliest records in the time window were compared -- narrow the window to cover the rest.'
            : ''),
      )
      load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not generate spatial-relationship candidates.')
    } finally {
      setGenerating(false)
    }
  }

  async function handleReview(row: SpatialRelationshipCandidate, status: 'confirmed' | 'rejected' | 'uncertain') {
    setBusyId(row.relationship_id)
    try {
      await api.relationships.review(row.relationship_id, status)
      load()
    } catch {
      // row stays in its current status, which is itself the signal
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <PageHeader
        title="Spatial Relationship Explorer"
        description="A spatially_associated candidate is only ever an explainable proximity fact -- 'these two records were close in space and time.' It is never a claim that they describe the same real-world event; that judgment belongs to the Conflict Review workflow, not here."
        actions={
          canManage && (
            <Button onClick={handleGenerate} disabled={generating}>
              {generating ? 'Generating…' : 'Generate candidates'}
            </Button>
          )
        }
      />

      {runResult && <div className="mb-4 rounded-md border border-accent-500/30 bg-accent-500/10 px-4 py-2 text-sm text-accent-300">{runResult}</div>}

      <div className="mb-4 flex gap-2">
        {REVIEW_FILTERS.map((s) => (
          <button
            key={s || 'all'}
            onClick={() => setReviewStatus(s)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              reviewStatus === s ? 'bg-accent-500/15 text-accent-400' : 'bg-charcoal-800 text-slate-400 hover:bg-charcoal-700'
            }`}
          >
            {s || 'all'}
          </button>
        ))}
      </div>

      {error && <ErrorState message={error} />}
      {!candidates && !error && <Spinner />}
      {candidates && candidates.length === 0 && <EmptyState message="No spatial-relationship candidates match this filter." />}
      {candidates && candidates.length > 0 && (
        <div className="space-y-3">
          {candidates.map((c) => (
            <Card key={c.relationship_id}>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm text-slate-200">
                    <span className="rounded-sm bg-charcoal-700 px-1.5 py-0.5 text-xs capitalize text-slate-400">{c.source_record_type}</span>{' '}
                    <span className="font-mono text-xs">{c.source_record_id.slice(0, 8)}</span>
                    <span className="mx-2 text-slate-500">&harr;</span>
                    <span className="rounded-sm bg-charcoal-700 px-1.5 py-0.5 text-xs capitalize text-slate-400">{c.target_record_type}</span>{' '}
                    <span className="font-mono text-xs">{c.target_record_id.slice(0, 8)}</span>
                  </div>
                  <p className="mt-2 text-sm text-slate-400">{c.explanation}</p>
                  <div className="mt-2 flex gap-4 text-xs text-slate-500">
                    <span>distance: {c.distance_m !== null ? `${c.distance_m.toFixed(1)}m` : 'n/a'}</span>
                    <span>time gap: {c.time_difference_seconds !== null ? `${c.time_difference_seconds.toFixed(0)}s` : 'n/a'}</span>
                    <span>rule: {c.rule_version}</span>
                  </div>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <StatusPill status={c.review_status} />
                  {canReview && c.review_status === 'candidate' && (
                    <div className="flex gap-1.5">
                      <Button variant="secondary" disabled={busyId === c.relationship_id} onClick={() => handleReview(c, 'confirmed')}>
                        Confirm
                      </Button>
                      <Button variant="danger" disabled={busyId === c.relationship_id} onClick={() => handleReview(c, 'rejected')}>
                        Reject
                      </Button>
                      <Button variant="secondary" disabled={busyId === c.relationship_id} onClick={() => handleReview(c, 'uncertain')}>
                        Uncertain
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
