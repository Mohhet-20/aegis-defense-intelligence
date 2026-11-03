import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { Assessment, Page } from '../types/api'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

export function AssessmentsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const [data, setData] = useState<Page<Assessment> | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [showForm, setShowForm] = useState(false)
  const [title, setTitle] = useState('')
  const [question, setQuestion] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  function load() {
    api.assessments
      .list({ page, page_size: 20, status: statusFilter || undefined })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [page, statusFilter])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    try {
      const created = await api.assessments.create({ title, question })
      setTitle('')
      setQuestion('')
      setShowForm(false)
      navigate(`/fusion/assessments/${created.id}`)
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not create assessment.')
    }
  }

  return (
    <div>
      <PageHeader
        title="Assessment Workspace"
        description="A bounded, versioned, explainable judgment -- confidence is always qualitative (low/moderate/high) with a stated rationale, never a fabricated probability. Every update is snapshotted before it happens."
        actions={canManage && <Button onClick={() => setShowForm((s) => !s)}>{showForm ? 'Cancel' : 'New assessment'}</Button>}
      />

      {showForm && (
        <Card className="mb-5 max-w-xl">
          <form onSubmit={handleCreate} className="space-y-3">
            <Field label="Title">
              <input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} required />
            </Field>
            <Field label="Question this assessment answers">
              <textarea className={inputClass} rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} required />
            </Field>
            {formError && <ErrorState message={formError} />}
            <Button type="submit">Create draft</Button>
          </form>
        </Card>
      )}

      <div className="mb-4 flex gap-2">
        {['', 'draft', 'in_review', 'published', 'archived'].map((s) => (
          <button
            key={s || 'all'}
            onClick={() => {
              setPage(1)
              setStatusFilter(s)
            }}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              statusFilter === s ? 'bg-accent-500/15 text-accent-400' : 'bg-charcoal-800 text-slate-400 hover:bg-charcoal-700'
            }`}
          >
            {s || 'all'}
          </button>
        ))}
      </div>

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No assessments match this filter." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            onRowClick={(row) => navigate(`/fusion/assessments/${row.id}`)}
            columns={[
              { header: 'Title', render: (r) => r.title },
              { header: 'Question', render: (r) => <span className="text-xs">{r.question}</span> },
              { header: 'Status', render: (r) => <StatusPill status={r.status} /> },
              { header: 'Confidence', render: (r) => (r.confidence_level ? <StatusPill status={r.confidence_level} /> : <span className="text-slate-500">not set</span>) },
              { header: 'Version', render: (r) => r.version },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
