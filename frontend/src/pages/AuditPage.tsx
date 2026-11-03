import { useCallback, useEffect, useState } from 'react'
import { governanceApi } from '../api/governance'
import type { AuditRecord, Page } from '../types/api'
import type { AuditFilters } from '../types/governance'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

const EMPTY: AuditFilters = { outcome: '' }

/** Audit explorer. Org-scoped on the server; administrators only (AUDIT_READ). */
export function AuditPage() {
  const [page, setPage] = useState(1)
  const [draft, setDraft] = useState<AuditFilters>(EMPTY)
  const [filters, setFilters] = useState<AuditFilters>(EMPTY)
  const [data, setData] = useState<Page<AuditRecord> | null>(null)
  const [actions, setActions] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<AuditRecord | null>(null)

  const load = useCallback(() => {
    governanceApi.audit(filters, page).then((d) => { setData(d); setError(null) }).catch((e) => setError(e.message))
  }, [filters, page])
  useEffect(load, [load])
  useEffect(() => { governanceApi.auditActions().then(setActions).catch(() => setActions([])) }, [])

  const set = (k: keyof AuditFilters, v: string) => setDraft((d) => ({ ...d, [k]: v }))
  const apply = (e: React.FormEvent) => { e.preventDefault(); setPage(1); setFilters(draft) }
  const toIso = (v?: string) => (v ? new Date(v).toISOString() : undefined)

  return (
    <div>
      <PageHeader
        title="Audit Explorer"
        description="Append-oriented record of significant actions in your organization. It is NOT tamper-proof: application code cannot edit or delete rows, but a database administrator can. Administrators only; other organizations' and system-level rows are never shown."
      />
      <Card className="mb-4">
        <form onSubmit={apply} className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <Field label="Action (exact)">
            <select className={inputClass} value={draft.action ?? ''} onChange={(e) => set('action', e.target.value)}>
              <option value="">any</option>
              {actions.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </Field>
          <Field label="Action prefix"><input className={inputClass} placeholder="lifecycle." value={draft.action_prefix ?? ''} onChange={(e) => set('action_prefix', e.target.value)} /></Field>
          <Field label="Outcome">
            <select className={inputClass} value={draft.outcome ?? ''} onChange={(e) => set('outcome', e.target.value)}>
              <option value="">any</option><option value="success">success</option><option value="failure">failure</option><option value="denied">denied</option>
            </select>
          </Field>
          <Field label="Actor user id"><input className={inputClass} value={draft.actor_user_id ?? ''} onChange={(e) => set('actor_user_id', e.target.value)} /></Field>
          <Field label="Resource type"><input className={inputClass} value={draft.target_type ?? ''} onChange={(e) => set('target_type', e.target.value)} /></Field>
          <Field label="Resource id"><input className={inputClass} value={draft.target_id ?? ''} onChange={(e) => set('target_id', e.target.value)} /></Field>
          <Field label="From"><input type="datetime-local" className={inputClass} onChange={(e) => set('created_from', toIso(e.target.value) ?? '')} /></Field>
          <Field label="To"><input type="datetime-local" className={inputClass} onChange={(e) => set('created_to', toIso(e.target.value) ?? '')} /></Field>
          <div className="flex items-end gap-2 md:col-span-4">
            <Button type="submit">Apply filters</Button>
            <Button variant="secondary" onClick={() => { setDraft(EMPTY); setFilters(EMPTY); setPage(1) }}>Reset</Button>
          </div>
        </form>
      </Card>
      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No audit records match these filters." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            onRowClick={setSelected}
            columns={[
              { header: 'When', render: (r) => new Date(r.created_at).toLocaleString() },
              { header: 'Action', render: (r) => r.action },
              { header: 'Outcome', render: (r) => <StatusPill status={r.outcome} /> },
              { header: 'Resource', render: (r) => (r.target_type ? `${r.target_type}:${r.target_id?.slice(0, 8) ?? ''}` : '--') },
              { header: 'Actor', render: (r) => (r.actor_user_id ? <span className="font-mono text-xs">{r.actor_user_id.slice(0, 8)}</span> : 'system') },
              { header: 'Request', render: (r) => <span className="font-mono text-xs">{r.request_id?.slice(0, 8) ?? '--'}</span> },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
      {selected && (
        <Modal title={`Audit event ${selected.id.slice(0, 8)}`} onClose={() => setSelected(null)}>
          <dl className="space-y-1 text-xs text-slate-300">
            <div><dt className="inline text-slate-500">Event id: </dt><dd className="inline font-mono">{selected.id}</dd></div>
            <div><dt className="inline text-slate-500">Timestamp: </dt><dd className="inline">{new Date(selected.created_at).toISOString()}</dd></div>
            <div><dt className="inline text-slate-500">Actor: </dt><dd className="inline font-mono">{selected.actor_user_id ?? 'system'}</dd></div>
            <div><dt className="inline text-slate-500">Organization: </dt><dd className="inline font-mono">{selected.organization_id}</dd></div>
            <div><dt className="inline text-slate-500">Action / outcome: </dt><dd className="inline">{selected.action} / {selected.outcome}</dd></div>
            <div><dt className="inline text-slate-500">Resource: </dt><dd className="inline font-mono">{selected.target_type ?? '--'} {selected.target_id ?? ''}</dd></div>
            <div><dt className="inline text-slate-500">Request id: </dt><dd className="inline font-mono">{selected.request_id ?? '--'}</dd></div>
          </dl>
          <div className="mt-3 text-xs text-slate-500">Details (secrets are redacted before storage)</div>
          <pre className="mt-1 max-h-64 overflow-auto rounded-sm bg-charcoal-900 p-3 text-xs text-slate-300">{JSON.stringify(selected.context_metadata, null, 2)}</pre>
        </Modal>
      )}
    </div>
  )
}
