import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { Evidence, Page } from '../types/api'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, inputClass } from '../components/ui/Primitives'

// Mirrors app/models/evidence.py EVIDENCE_TYPES.
const EVIDENCE_TYPES = ['observation', 'ingestion_record', 'sensor_observation', 'report', 'analyst_note', 'document', 'media_reference']
// Types this platform ever stores actual text for -- the rest are
// references that must point at a real record or URI instead
// (evidence_service.validate_evidence_payload enforces this).
const CONTENT_TYPES = new Set(['report', 'analyst_note'])
const REFERENCE_TYPES = new Set(['document', 'media_reference'])

export function EvidencePage() {
  const { user } = useAuth()
  const [page, setPage] = useState(1)
  const [typeFilter, setTypeFilter] = useState('')
  const [data, setData] = useState<Page<Evidence> | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [showForm, setShowForm] = useState(false)
  const [evidenceType, setEvidenceType] = useState(EVIDENCE_TYPES[4])
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [eventId, setEventId] = useState('')
  const [content, setContent] = useState('')
  const [externalUri, setExternalUri] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  function load() {
    api.evidence
      .list({ page, page_size: 20, evidence_type: typeFilter || undefined })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [page, typeFilter])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    try {
      await api.evidence.create({
        evidence_type: evidenceType,
        title,
        summary: summary || undefined,
        event_id: evidenceType === 'observation' ? eventId || undefined : undefined,
        content: CONTENT_TYPES.has(evidenceType) ? content || undefined : undefined,
        external_reference_uri: REFERENCE_TYPES.has(evidenceType) ? externalUri || undefined : undefined,
      })
      setTitle('')
      setSummary('')
      setEventId('')
      setContent('')
      setExternalUri('')
      setShowForm(false)
      load()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not create evidence item.')
    }
  }

  return (
    <div>
      <PageHeader
        title="Evidence Library"
        description="A reference layer, not media storage -- this platform never fetches or stores the content behind a document/media reference, only the pointer to it (an event, a URI, or a short analyst-authored text)."
        actions={canManage && <Button onClick={() => setShowForm((s) => !s)}>{showForm ? 'Cancel' : 'Add evidence item'}</Button>}
      />

      {showForm && (
        <Card className="mb-5 max-w-xl">
          <form onSubmit={handleCreate} className="space-y-3">
            <Field label="Evidence type">
              <select className={inputClass} value={evidenceType} onChange={(e) => setEvidenceType(e.target.value)}>
                {EVIDENCE_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Title">
              <input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} required />
            </Field>
            <Field label="Summary (optional)">
              <input className={inputClass} value={summary} onChange={(e) => setSummary(e.target.value)} />
            </Field>
            {evidenceType === 'observation' && (
              <Field label="Linked event ID">
                <input className={inputClass} value={eventId} onChange={(e) => setEventId(e.target.value)} required placeholder="the real event this evidence points at" />
              </Field>
            )}
            {CONTENT_TYPES.has(evidenceType) && (
              <Field label="Content">
                <textarea className={inputClass} rows={4} value={content} onChange={(e) => setContent(e.target.value)} required />
              </Field>
            )}
            {REFERENCE_TYPES.has(evidenceType) && (
              <Field label="External reference URI">
                <input className={inputClass} value={externalUri} onChange={(e) => setExternalUri(e.target.value)} required placeholder="never fetched by this platform" />
              </Field>
            )}
            {formError && <ErrorState message={formError} />}
            <Button type="submit">Create</Button>
          </form>
        </Card>
      )}

      <div className="mb-4 flex gap-2">
        {['', ...EVIDENCE_TYPES].map((t) => (
          <button
            key={t || 'all'}
            onClick={() => {
              setPage(1)
              setTypeFilter(t)
            }}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              typeFilter === t ? 'bg-accent-500/15 text-accent-400' : 'bg-charcoal-800 text-slate-400 hover:bg-charcoal-700'
            }`}
          >
            {t || 'all'}
          </button>
        ))}
      </div>

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No evidence items match this filter." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            columns={[
              { header: 'Title', render: (r) => r.title },
              { header: 'Type', render: (r) => <span className="text-xs">{r.evidence_type}</span> },
              {
                header: 'Points at',
                render: (r) =>
                  r.event_id ? (
                    <span className="font-mono text-xs">event:{r.event_id.slice(0, 8)}</span>
                  ) : r.external_reference_uri ? (
                    <span className="text-xs text-slate-400">{r.external_reference_uri}</span>
                  ) : r.content ? (
                    <span className="text-xs text-slate-400">{r.content.slice(0, 60)}{r.content.length > 60 ? '…' : ''}</span>
                  ) : (
                    '--'
                  ),
              },
              { header: 'Created', render: (r) => new Date(r.created_at).toLocaleDateString() },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
