import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../context/auth'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { LoadState } from '../components/investigations/InvestigationBits'
import { fmtTime, useLoad, errorText } from '../components/investigations/useLoad'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, StatTile, StatusPill, inputClass } from '../components/ui/Primitives'

const STATUSES = ['draft', 'open', 'active', 'pending_review', 'closed', 'archived']

export function InvestigationsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [sort, setSort] = useState('created_at:desc')
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ title: '', description: '', priority: 'normal', tags: '', restricted: false, draft: false })
  const [formError, setFormError] = useState<string | null>(null)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'
  const [sortBy, sortDir] = sort.split(':')
  const list = useLoad(
    () => api.workspace.list({ page, status: status || undefined, priority: priority || undefined, q: q || undefined, sortBy, sortDir }),
    [page, status, priority, q, sort],
  )
  const summary = useLoad(() => api.workspace.dashboard(), [])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    try {
      const created = await api.workspace.create({
        title: form.title, description: form.description || undefined, priority: form.priority,
        tags: form.tags.split(',').map((t) => t.trim()).filter(Boolean), is_restricted: form.restricted, initial_status: form.draft ? 'draft' : 'open',
      })
      navigate(`/investigations/${created.id}`)
    } catch (err) {
      setFormError(errorText(err, 'Could not create investigation.'))
    }
  }

  return (
    <div>
      <PageHeader
        title="Investigations"
        description="Case workspace: link records, register evidence, review timelines and record findings for human review."
        actions={canManage && <Button onClick={() => setShowForm((s) => !s)}>{showForm ? 'Cancel' : 'New investigation'}</Button>}
      />

      <LoadState loading={summary.loading} error={summary.error}>
        {summary.data && (
          <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <StatTile label="Visible to you" value={summary.data.total} />
            <StatTile label="Open" value={summary.data.by_status.open ?? 0} />
            <StatTile label="Under review" value={summary.data.by_status.pending_review ?? 0} />
            <StatTile label="Open review questions" value={summary.data.open_review_questions} hint={`${summary.data.review_questions_assigned_to_me} assigned to you`} />
            <StatTile label="High / urgent (not closed)" value={(summary.data.open_by_priority.high ?? 0) + (summary.data.open_by_priority.urgent ?? 0)} />
          </div>
        )}
      </LoadState>

      {showForm && (
        <Card className="mb-5 max-w-lg">
          <form onSubmit={handleCreate} className="space-y-3">
            <Field label="Title"><input className={inputClass} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required maxLength={300} /></Field>
            <Field label="Description"><textarea className={inputClass} rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} maxLength={4000} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Priority"><select className={inputClass} value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>{['low', 'normal', 'high', 'urgent'].map((p) => <option key={p}>{p}</option>)}</select></Field>
              <Field label="Tags (comma separated)"><input className={inputClass} value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} /></Field>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={form.restricted} onChange={(e) => setForm({ ...form, restricted: e.target.checked })} /> Restrict to owner, members and administrators</label>
            <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={form.draft} onChange={(e) => setForm({ ...form, draft: e.target.checked })} /> Start as draft</label>
            {formError && <ErrorState message={formError} />}
            <Button type="submit">Create</Button>
          </form>
        </Card>
      )}

      <Card className="mb-4">
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Search"><input className={inputClass} value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} placeholder="Title or description" /></Field>
          <Field label="Status"><select className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}><option value="">Active (hides archived)</option>{STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}</select></Field>
          <Field label="Priority"><select className={inputClass} value={priority} onChange={(e) => { setPriority(e.target.value); setPage(1) }}><option value="">Any</option>{['low', 'normal', 'high', 'urgent'].map((p) => <option key={p}>{p}</option>)}</select></Field>
          <Field label="Sort"><select className={inputClass} value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="created_at:desc">Newest</option><option value="updated_at:desc">Recently updated</option><option value="title:asc">Title A-Z</option><option value="priority:desc">Priority</option>
          </select></Field>
        </div>
      </Card>

      <LoadState loading={list.loading && !list.data} error={list.error}>
        {list.data && list.data.items.length === 0 && <EmptyState message="No investigations match these filters." />}
        {list.data && list.data.items.length > 0 && (
          <>
            <DataTable
              rows={list.data.items}
              onRowClick={(row) => navigate(`/investigations/${row.id}`)}
              columns={[
                { header: 'Title', render: (r) => r.title },
                { header: 'Status', render: (r) => <StatusPill status={r.status} /> },
                { header: 'Priority', render: (r) => <StatusPill status={r.priority} /> },
                { header: 'Tags', render: (r) => r.tags.join(', ') || '--' },
                { header: 'Access', render: (r) => (r.is_restricted ? 'restricted' : 'org') },
                { header: 'Updated', render: (r) => fmtTime(r.updated_at) },
              ]}
            />
            <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onPageChange={setPage} />
          </>
        )}
      </LoadState>

      {summary.data && summary.data.recent_activity.length > 0 && (
        <Card className="mt-5">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Recent activity</h2>
          <ul className="space-y-1 text-sm">{summary.data.recent_activity.map((a) => (
            <li key={a.id}><button className="text-accent-400 hover:underline" onClick={() => navigate(`/investigations/${a.id}`)}>{a.title}</button> <span className="text-xs text-slate-500">{a.status} · updated {fmtTime(a.updated_at)}</span></li>
          ))}</ul>
        </Card>
      )}
    </div>
  )
}
