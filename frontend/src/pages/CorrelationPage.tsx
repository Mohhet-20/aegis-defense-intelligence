import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { EventCorrelation, Page } from '../types/api'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { Button, EmptyState, ErrorState, PageHeader, Spinner, StatusPill } from '../components/ui/Primitives'

export function CorrelationPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<EventCorrelation> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [recomputing, setRecomputing] = useState(false)
  const [recomputeMessage, setRecomputeMessage] = useState<string | null>(null)
  const [reviewingId, setReviewingId] = useState<string | null>(null)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst'

  function load() {
    api.correlation
      .list(page, 20)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [page])

  async function handleRecompute() {
    setRecomputing(true)
    setRecomputeMessage(null)
    try {
      const result = await api.correlation.recompute({})
      setRecomputeMessage(
        `Considered ${result.events_considered} events / ${result.pairs_considered} pairs -- created ${result.correlations_created} new candidate(s), ${result.already_existed} already existed (rule v${result.rule_version}).`,
      )
      load()
    } catch (err) {
      setRecomputeMessage(err instanceof ApiError ? err.message : 'Recompute failed.')
    } finally {
      setRecomputing(false)
    }
  }

  async function handleReview(row: EventCorrelation, status: 'confirmed' | 'rejected') {
    setReviewingId(row.id)
    try {
      await api.correlation.review(row.id, status)
      load()
    } catch {
      // surfaced implicitly by the row staying in "candidate" state
    } finally {
      setReviewingId(null)
    }
  }

  return (
    <div>
      <PageHeader
        title="Correlation Review"
        description="Rule-based candidate relationships between events -- a transparent grouping for analyst review, never an assertion of fact. Recompute is an explicit, authorized, auditable operation."
        actions={
          canManage && (
            <Button onClick={handleRecompute} disabled={recomputing}>
              {recomputing ? 'Recomputing…' : 'Recompute candidates'}
            </Button>
          )
        }
      />

      {recomputeMessage && <div className="mb-4 text-sm text-slate-300">{recomputeMessage}</div>}
      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && (
        <EmptyState message="No correlation candidates yet -- register events with overlapping time/location, then recompute." />
      )}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            onRowClick={(row) => navigate(`/events/${row.event_a_id}`)}
            columns={[
              { header: 'Event A', render: (r) => <span className="font-mono text-xs">{r.event_a_id.slice(0, 8)}</span> },
              { header: 'Event B', render: (r) => <span className="font-mono text-xs">{r.event_b_id.slice(0, 8)}</span> },
              { header: 'Reasons', render: (r) => <span className="text-xs">{r.reasons.join(', ')}</span> },
              { header: 'Match strength', render: (r) => (r.match_strength !== null ? r.match_strength.toFixed(2) : '--') },
              {
                header: 'Temporal Δ',
                render: (r) => (r.temporal_delta_seconds !== null ? `${Math.round(r.temporal_delta_seconds)}s` : '--'),
              },
              {
                header: 'Spatial Δ',
                render: (r) => (r.spatial_delta_meters !== null ? `${Math.round(r.spatial_delta_meters)}m` : '--'),
              },
              { header: 'Review status', render: (r) => <StatusPill status={r.review_status} /> },
              {
                header: 'Review',
                render: (r) =>
                  canManage && r.review_status === 'candidate' ? (
                    <div className="flex gap-1.5" onClick={(e) => e.stopPropagation()}>
                      <Button variant="secondary" disabled={reviewingId === r.id} onClick={() => handleReview(r, 'confirmed')}>
                        Confirm
                      </Button>
                      <Button variant="danger" disabled={reviewingId === r.id} onClick={() => handleReview(r, 'rejected')}>
                        Reject
                      </Button>
                    </div>
                  ) : (
                    <span className="text-slate-500">{r.review_status !== 'candidate' ? 'reviewed' : 'read-only'}</span>
                  ),
              },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
