import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { Conflict, Page, ReviewHistoryEntry } from '../types/api'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

// Mirrors app/models/conflict.py -- "unresolved" is the starting state,
// never a target an analyst resolves TO.
const RESOLUTION_STATUSES = ['explained', 'accepted', 'corrected', 'superseded']

export function ConflictsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [reviewStatus, setReviewStatus] = useState('unresolved')
  const [data, setData] = useState<Page<Conflict> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [detecting, setDetecting] = useState(false)
  const [detectMessage, setDetectMessage] = useState<string | null>(null)
  const [resolvingId, setResolvingId] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [historyFor, setHistoryFor] = useState<string | null>(null)
  const [history, setHistory] = useState<ReviewHistoryEntry[] | null>(null)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  function load() {
    api.conflicts
      .list({ page, page_size: 20, review_status: reviewStatus || undefined })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [page, reviewStatus])

  async function handleDetect() {
    setDetecting(true)
    setDetectMessage(null)
    try {
      const result = await api.conflicts.detect({})
      setDetectMessage(
        `Considered ${result.pairs_considered} already-correlated pair(s) -- found ${result.conflicts_created} new conflict(s), updated ${result.conflicts_updated} (rule v${result.rule_version}).`,
      )
      load()
    } catch (err) {
      setDetectMessage(err instanceof ApiError ? err.message : 'Conflict detection failed.')
    } finally {
      setDetecting(false)
    }
  }

  async function handleResolve(row: Conflict, status: string) {
    setResolvingId(row.id)
    try {
      await api.conflicts.resolve(row.id, status, note || undefined)
      setNote('')
      load()
    } catch {
      // row stays unresolved, which is itself the visible signal
    } finally {
      setResolvingId(null)
    }
  }

  async function toggleHistory(row: Conflict) {
    if (historyFor === row.id) {
      setHistoryFor(null)
      setHistory(null)
      return
    }
    setHistoryFor(row.id)
    try {
      setHistory(await api.conflicts.history(row.id))
    } catch {
      setHistory([])
    }
  }

  return (
    <div>
      <PageHeader
        title="Conflict Review Center"
        description="Only pairs that already have an existing correlation are ever checked for conflict -- missing information is never treated as a disagreement. Detection is an explicit, auditable action; it never invents a resolution on its own."
        actions={
          canManage && (
            <Button onClick={handleDetect} disabled={detecting}>
              {detecting ? 'Detecting…' : 'Detect conflicts'}
            </Button>
          )
        }
      />

      {detectMessage && <div className="mb-4 text-sm text-slate-300">{detectMessage}</div>}

      <div className="mb-4 flex gap-2">
        {['unresolved', 'explained', 'accepted', 'corrected', 'superseded', ''].map((s) => (
          <button
            key={s || 'all'}
            onClick={() => {
              setPage(1)
              setReviewStatus(s)
            }}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              reviewStatus === s ? 'bg-accent-500/15 text-accent-400' : 'bg-charcoal-800 text-slate-400 hover:bg-charcoal-700'
            }`}
          >
            {s || 'all'}
          </button>
        ))}
      </div>

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No conflicts match this filter." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            columns={[
              {
                header: 'Event A',
                render: (r) => (
                  <span
                    className="cursor-pointer font-mono text-xs text-accent-400 hover:underline"
                    onClick={(e) => {
                      e.stopPropagation()
                      navigate(`/events/${r.event_a_id}`)
                    }}
                  >
                    {r.event_a_id.slice(0, 8)}
                  </span>
                ),
              },
              {
                header: 'Event B',
                render: (r) => (
                  <span
                    className="cursor-pointer font-mono text-xs text-accent-400 hover:underline"
                    onClick={(e) => {
                      e.stopPropagation()
                      navigate(`/events/${r.event_b_id}`)
                    }}
                  >
                    {r.event_b_id.slice(0, 8)}
                  </span>
                ),
              },
              {
                header: 'Conflicting fields',
                render: (r) => (
                  <ul className="space-y-0.5 text-xs">
                    {r.conflicting_fields.map((f, i) => (
                      <li key={i}>
                        <span className="text-slate-300">{f.field}</span>{' '}
                        <span className="text-slate-500">
                          ({f.rule}: {JSON.stringify(f.value_a)} vs {JSON.stringify(f.value_b)})
                        </span>
                      </li>
                    ))}
                  </ul>
                ),
              },
              { header: 'Status', render: (r) => <StatusPill status={r.review_status} /> },
              {
                header: 'Resolution',
                render: (r) =>
                  canManage && r.review_status === 'unresolved' ? (
                    <div className="flex flex-wrap gap-1.5" onClick={(e) => e.stopPropagation()}>
                      {RESOLUTION_STATUSES.map((s) => (
                        <Button key={s} variant="secondary" disabled={resolvingId === r.id} onClick={() => handleResolve(r, s)}>
                          {s}
                        </Button>
                      ))}
                    </div>
                  ) : (
                    <span className="text-xs text-slate-500">{r.resolution_note ?? '--'}</span>
                  ),
              },
              {
                header: '',
                render: (r) => (
                  <Button variant="secondary" onClick={() => toggleHistory(r)}>
                    {historyFor === r.id ? 'Hide history' : 'History'}
                  </Button>
                ),
              },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />

          {canManage && (
            <Card className="mt-4 max-w-md">
              <Field label="Resolution note (applies to the next resolution action above)">
                <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Different sensors genuinely saw different things." />
              </Field>
            </Card>
          )}

          {historyFor && (
            <Card className="mt-4">
              <h3 className="mb-2 text-sm font-semibold text-slate-200">Resolution history</h3>
              {history === null && <Spinner />}
              {history && history.length === 0 && <p className="text-sm text-slate-500">No resolution recorded yet.</p>}
              {history && history.length > 0 && (
                <ul className="space-y-2">
                  {history.map((h) => (
                    <li key={h.id} className="border-b border-charcoal-700/50 py-2 text-sm last:border-0">
                      <div className="flex justify-between">
                        <span className="text-slate-300">{h.action}</span>
                        <span className="text-xs text-slate-500">{new Date(h.created_at).toLocaleString()}</span>
                      </div>
                      <div className="text-xs text-slate-500">{JSON.stringify(h.context_metadata)}</div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
        </>
      )}
    </div>
  )
}
