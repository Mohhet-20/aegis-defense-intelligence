import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { EvidenceRelationship, Page, ReviewHistoryEntry } from '../types/api'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

// Mirrors app/models/evidence_relationship.py -- never a freeform string.
const RELATIONSHIP_TYPES = [
  'supports',
  'contradicts',
  'corroborates',
  'derived_from',
  'duplicate_candidate',
  'temporally_associated',
  'spatially_associated',
  'shares_source_identifier',
  'analyst_linked',
]

export function RelationshipsPage() {
  const { user } = useAuth()
  const [page, setPage] = useState(1)
  const [reviewStatus, setReviewStatus] = useState<string>('candidate')
  const [data, setData] = useState<Page<EvidenceRelationship> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [historyFor, setHistoryFor] = useState<string | null>(null)
  const [history, setHistory] = useState<ReviewHistoryEntry[] | null>(null)

  const [showForm, setShowForm] = useState(false)
  const [sourceRefType, setSourceRefType] = useState('event')
  const [sourceRefId, setSourceRefId] = useState('')
  const [targetRefType, setTargetRefType] = useState('event')
  const [targetRefId, setTargetRefId] = useState('')
  const [relationshipType, setRelationshipType] = useState(RELATIONSHIP_TYPES[0])
  const [explanation, setExplanation] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  function load() {
    api.relationships
      .list({ page, page_size: 20, review_status: reviewStatus || undefined })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [page, reviewStatus])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    try {
      await api.relationships.create({
        source_ref_type: sourceRefType,
        source_ref_id: sourceRefId,
        target_ref_type: targetRefType,
        target_ref_id: targetRefId,
        relationship_type: relationshipType,
        explanation,
      })
      setSourceRefId('')
      setTargetRefId('')
      setExplanation('')
      setShowForm(false)
      load()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not create relationship.')
    }
  }

  async function handleReview(row: EvidenceRelationship, status: 'confirmed' | 'rejected' | 'uncertain') {
    setBusyId(row.id)
    try {
      await api.relationships.review(row.id, status)
      load()
    } catch {
      // row stays in its current status, which is itself the signal
    } finally {
      setBusyId(null)
    }
  }

  async function handleReverse(row: EvidenceRelationship) {
    setBusyId(row.id)
    try {
      await api.relationships.reverse(row.id)
      load()
    } catch {
      // no-op -- reverse is refused server-side if never reviewed
    } finally {
      setBusyId(null)
    }
  }

  async function toggleHistory(row: EvidenceRelationship) {
    if (historyFor === row.id) {
      setHistoryFor(null)
      setHistory(null)
      return
    }
    setHistoryFor(row.id)
    try {
      setHistory(await api.relationships.history(row.id))
    } catch {
      setHistory([])
    }
  }

  function endpointLabel(type: string | null, id: string | null): string {
    if (!id) return '--'
    return `${type}:${id.slice(0, 8)}`
  }

  return (
    <div>
      <PageHeader
        title="Evidence Relationship Workspace"
        description="Analyst-drawn and rule-based links between events and evidence -- each one stays a candidate until a human confirms, rejects, or marks it uncertain. Reversing a confirmed link is audited, never a silent delete."
        actions={canManage && <Button onClick={() => setShowForm((s) => !s)}>{showForm ? 'Cancel' : 'Draw a relationship'}</Button>}
      />

      {showForm && (
        <Card className="mb-5 max-w-xl">
          <form onSubmit={handleCreate} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Source type">
                <select className={inputClass} value={sourceRefType} onChange={(e) => setSourceRefType(e.target.value)}>
                  <option value="event">event</option>
                  <option value="evidence">evidence</option>
                </select>
              </Field>
              <Field label="Source ID">
                <input className={inputClass} value={sourceRefId} onChange={(e) => setSourceRefId(e.target.value)} required placeholder="event or evidence id" />
              </Field>
              <Field label="Target type">
                <select className={inputClass} value={targetRefType} onChange={(e) => setTargetRefType(e.target.value)}>
                  <option value="event">event</option>
                  <option value="evidence">evidence</option>
                </select>
              </Field>
              <Field label="Target ID">
                <input className={inputClass} value={targetRefId} onChange={(e) => setTargetRefId(e.target.value)} required placeholder="event or evidence id" />
              </Field>
            </div>
            <Field label="Relationship type">
              <select className={inputClass} value={relationshipType} onChange={(e) => setRelationshipType(e.target.value)}>
                {RELATIONSHIP_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Explanation (why these two are linked)">
              <textarea className={inputClass} rows={3} value={explanation} onChange={(e) => setExplanation(e.target.value)} required />
            </Field>
            {formError && <ErrorState message={formError} />}
            <Button type="submit">Create relationship</Button>
          </form>
        </Card>
      )}

      <div className="mb-4 flex gap-2">
        {['candidate', 'confirmed', 'rejected', 'uncertain', ''].map((s) => (
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
      {data && data.items.length === 0 && <EmptyState message="No relationships match this filter." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            columns={[
              {
                header: 'Source',
                render: (r) => (
                  <span className="font-mono text-xs">{endpointLabel(r.source_event_id ? 'event' : 'evidence', r.source_event_id ?? r.source_evidence_id)}</span>
                ),
              },
              {
                header: 'Target',
                render: (r) => (
                  <span className="font-mono text-xs">{endpointLabel(r.target_event_id ? 'event' : 'evidence', r.target_event_id ?? r.target_evidence_id)}</span>
                ),
              },
              { header: 'Type', render: (r) => <span className="text-xs">{r.relationship_type}</span> },
              { header: 'Origin', render: (r) => <span className="text-xs text-slate-500">{r.origin}</span> },
              { header: 'Explanation', render: (r) => <span className="text-xs">{r.explanation}</span> },
              {
                header: 'Status',
                render: (r) => (
                  <div className="flex items-center gap-1.5">
                    <StatusPill status={r.review_status} />
                    {r.is_reversed && <span className="text-xs text-status-warning">reversed</span>}
                  </div>
                ),
              },
              {
                header: 'Actions',
                render: (r) => (
                  <div className="flex flex-wrap gap-1.5" onClick={(e) => e.stopPropagation()}>
                    {canManage && r.review_status === 'candidate' && (
                      <>
                        <Button variant="secondary" disabled={busyId === r.id} onClick={() => handleReview(r, 'confirmed')}>
                          Confirm
                        </Button>
                        <Button variant="danger" disabled={busyId === r.id} onClick={() => handleReview(r, 'rejected')}>
                          Reject
                        </Button>
                        <Button variant="secondary" disabled={busyId === r.id} onClick={() => handleReview(r, 'uncertain')}>
                          Uncertain
                        </Button>
                      </>
                    )}
                    {canManage && r.review_status !== 'candidate' && (
                      <Button variant="secondary" disabled={busyId === r.id} onClick={() => handleReverse(r)}>
                        Reverse
                      </Button>
                    )}
                    <Button variant="secondary" onClick={() => toggleHistory(r)}>
                      {historyFor === r.id ? 'Hide history' : 'History'}
                    </Button>
                  </div>
                ),
              },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />

          {historyFor && (
            <Card className="mt-4">
              <h3 className="mb-2 text-sm font-semibold text-slate-200">Review history</h3>
              {history === null && <Spinner />}
              {history && history.length === 0 && <p className="text-sm text-slate-500">No review actions recorded yet.</p>}
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
