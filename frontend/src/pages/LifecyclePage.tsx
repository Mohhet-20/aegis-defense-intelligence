import { useCallback, useEffect, useState } from 'react'
import { governanceApi } from '../api/governance'
import type { Page } from '../types/api'
import type { AuditRetentionReport, LifecyclePolicies, LifecyclePreview, LifecycleRequest } from '../types/governance'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { Button, Card, ErrorState, Field, Modal, PageHeader, Spinner, StatusPill, Tabs, inputClass } from '../components/ui/Primitives'

type Confirm = { title: string; body: string; run: () => Promise<unknown> } | null

/** Data lifecycle workspace: classification, retention, dry-run preview, approvals. */
export function LifecyclePage() {
  const [tab, setTab] = useState('policies')
  const [policies, setPolicies] = useState<LifecyclePolicies | null>(null)
  const [retention, setRetention] = useState<AuditRetentionReport | null>(null)
  const [preview, setPreview] = useState<LifecyclePreview | null>(null)
  const [previewType, setPreviewType] = useState('scenario_run')
  const [requests, setRequests] = useState<Page<LifecycleRequest> | null>(null)
  const [page, setPage] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<Confirm>(null)
  const [form, setForm] = useState({ resource_type: 'scenario_run', resource_id: '', action: 'delete', reason: '' })

  const loadRequests = useCallback(() => { governanceApi.lifecycleRequests(page).then(setRequests).catch((e) => setError(e.message)) }, [page])
  useEffect(() => {
    governanceApi.lifecyclePolicies().then(setPolicies).catch((e) => setError(e.message))
    governanceApi.auditRetention().then(setRetention).catch(() => setRetention(null))
  }, [])
  useEffect(loadRequests, [loadRequests])

  const run = async (fn: () => Promise<LifecycleRequest | unknown>, ok: string) => {
    setError(null); setNotice(null)
    try {
      const r = (await fn()) as LifecycleRequest | undefined
      // The server status is the truth: only 'executed' means the operation completed.
      if (r && r.status === 'cleanup_pending') setNotice(`Database change committed but file cleanup FAILED (${r.failure_reason}). Press Execute again to retry.`)
      else if (r && r.status === 'failed') setError(`Operation failed, nothing was changed: ${r.failure_reason}`)
      else setNotice(ok)
      loadRequests()
    } catch (e) { setError((e as Error).message) }
  }

  const managed = policies?.items.filter((i) => i.managed) ?? []

  return (
    <div>
      <PageHeader
        title="Data Lifecycle"
        description="Classification, retention and controlled archive/deletion. Deletion needs a request, a dry-run impact check, and approval (by a different administrator unless configured otherwise). Evidence, investigations, assessments, events and audit records are never deleted here."
      />
      {error && <ErrorState message={typeof error === 'string' ? error : 'Error'} />}
      {notice && <div className="mb-3 rounded-md border border-accent-500/40 bg-accent-500/10 px-3 py-2 text-sm text-slate-200">{notice}</div>}
      <Tabs tabs={[{ key: 'policies', label: 'Classification & retention' }, { key: 'preview', label: 'Dry-run preview' }, { key: 'requests', label: 'Requests' }]} active={tab} onChange={setTab} />
      {!policies && !error && <Spinner />}

      {tab === 'policies' && policies && (
        <div className="space-y-4">
          <DataTable
            rows={policies.items.map((i) => ({ ...i, id: i.resource_type }))}
            columns={[
              { header: 'Record type', render: (i) => i.label },
              { header: 'Classification', render: (i) => <StatusPill status={i.classification} /> },
              { header: 'Allowed operations', render: (i) => (i.actions.length ? i.actions.join(', ') : <span className="text-slate-500">none (retain / supersede)</span>) },
              { header: 'Retention window', render: (i) => (i.retention_days ? `${i.retention_days} days` : <span className="text-slate-500">{i.managed ? 'not set' : 'n/a'}</span>) },
              { header: 'Semantics', render: (i) => <span className="text-xs text-slate-400">{i.semantics}</span> },
            ]}
          />
          <Card>
            <div className="text-sm text-slate-200">Audit history retention</div>
            <p className="mt-1 text-xs text-slate-400">{policies.audit_note}</p>
            {retention && <p className="mt-1 text-xs text-slate-300">{retention.total} audit records stored{retention.retention_days ? `; ${retention.eligible_for_external_archival} older than ${retention.retention_days} days (eligible for external archival)` : '; no retention window configured'}.</p>}
            <p className="mt-1 text-xs text-slate-500">Separate approver required: {String(policies.require_separate_approver)}</p>
          </Card>
        </div>
      )}

      {tab === 'preview' && (
        <div className="space-y-3">
          <div className="flex items-end gap-3">
            <Field label="Record type">
              <select className={inputClass} value={previewType} onChange={(e) => setPreviewType(e.target.value)}>
                {managed.map((m) => <option key={m.resource_type} value={m.resource_type}>{m.label}</option>)}
              </select>
            </Field>
            <Button onClick={() => governanceApi.lifecyclePreview(previewType).then((p) => { setPreview(p); setError(null) }).catch((e) => setError(e.message))}>Preview eligible records</Button>
          </div>
          <p className="text-xs text-slate-500">A preview changes nothing. It lists records past their retention window and any blockers (e.g. media still referenced by evidence).</p>
          {preview && (
            <>
              {preview.note && <div className="text-sm text-slate-400">{preview.note}</div>}
              {preview.items.length > 0 && (
                <DataTable
                  rows={preview.items.map((i) => ({ ...i, id: i.resource_id }))}
                  columns={[
                    { header: 'Record', render: (i) => <div>{i.label}<div className="font-mono text-[10px] text-slate-500">{i.resource_id}</div></div> },
                    { header: 'Created', render: (i) => new Date(i.created_at).toLocaleDateString() },
                    { header: 'Impact', render: (i) => <span className="text-xs">{JSON.stringify(i.impact.affected)}</span> },
                    { header: 'Status', render: (i) => (i.impact.executable ? <StatusPill status="eligible" /> : <span className="text-xs text-status-critical">blocked: {i.impact.blockers.join('; ')}</span>) },
                    {
                      header: '', render: (i) => i.impact.executable ? (
                        <Button variant="secondary" onClick={() => { setForm({ resource_type: preview.resource_type, resource_id: i.resource_id, action: preview.action ?? 'delete', reason: `Past ${preview.retention_days}-day retention window` }); setTab('requests') }}>Request…</Button>
                      ) : null,
                    },
                  ]}
                />
              )}
              <div className="text-xs text-slate-500">{preview.total_eligible} eligible{preview.truncated ? ' (list truncated to the batch limit)' : ''}.</div>
            </>
          )}
        </div>
      )}

      {tab === 'requests' && (
        <div className="space-y-4">
          <Card>
            <h3 className="mb-2 text-sm font-semibold text-slate-100">New request</h3>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
              <Field label="Record type">
                <select className={inputClass} value={form.resource_type} onChange={(e) => { const m = managed.find((x) => x.resource_type === e.target.value); setForm({ ...form, resource_type: e.target.value, action: m?.actions[0] ?? 'delete' }) }}>
                  {managed.map((m) => <option key={m.resource_type} value={m.resource_type}>{m.label}</option>)}
                </select>
              </Field>
              <Field label="Record id"><input className={inputClass} value={form.resource_id} onChange={(e) => setForm({ ...form, resource_id: e.target.value })} /></Field>
              <Field label="Operation"><input className={inputClass} value={form.action} readOnly /></Field>
              <Field label="Reason (required)"><input className={inputClass} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
            </div>
            <div className="mt-3"><Button disabled={!form.resource_id || form.reason.length < 5}
              onClick={() => run(() => governanceApi.createLifecycleRequest({ ...form, action: form.action as 'archive' | 'delete' }), 'Request created; the dry-run impact is stored with it.')}>Create request</Button></div>
          </Card>
          {requests && (
            <>
              <DataTable
                rows={requests.items}
                columns={[
                  { header: 'Target', render: (r) => <div>{r.resource_type}<div className="font-mono text-[10px] text-slate-500">{r.resource_id}</div></div> },
                  { header: 'Operation', render: (r) => r.action },
                  { header: 'Status', render: (r) => <div><StatusPill status={r.status} />{r.failure_reason && <div className="mt-1 text-[11px] text-status-critical">{r.failure_reason}</div>}</div> },
                  { header: 'Reason', render: (r) => <span className="text-xs">{r.reason}</span> },
                  { header: 'Affected', render: (r) => <span className="text-xs">{JSON.stringify(r.impact?.affected ?? {})}</span> },
                  {
                    header: 'Actions',
                    render: (r) => (
                      <div className="flex flex-wrap gap-1.5">
                        {r.status === 'pending' && <Button onClick={() => run(() => governanceApi.approve(r.id), 'Approved.')}>Approve</Button>}
                        {r.status === 'pending' && <Button variant="secondary" onClick={() => run(() => governanceApi.reject(r.id), 'Rejected.')}>Reject</Button>}
                        {(r.status === 'approved' || r.status === 'cleanup_pending') && (
                          <Button variant="danger" onClick={() => setConfirm({
                            title: r.status === 'cleanup_pending' ? 'Retry file cleanup' : `Execute ${r.action}`,
                            body: `This will ${r.action} ${r.resource_type} ${r.resource_id}. Affected: ${JSON.stringify(r.impact?.affected ?? {})}. ${r.action === 'delete' ? 'Deletion cannot be undone.' : ''}`,
                            run: () => run(() => governanceApi.execute(r.id), `${r.action} completed.`),
                          })}>{r.status === 'cleanup_pending' ? 'Retry cleanup' : 'Execute…'}</Button>
                        )}
                        {(r.status === 'pending' || r.status === 'approved') && <Button variant="secondary" onClick={() => run(() => governanceApi.cancel(r.id), 'Cancelled.')}>Cancel</Button>}
                      </div>
                    ),
                  },
                ]}
              />
              <Pagination page={requests.page} pageSize={requests.page_size} total={requests.total} onPageChange={setPage} />
            </>
          )}
        </div>
      )}

      {confirm && (
        <Modal title={confirm.title} onClose={() => setConfirm(null)}>
          <p className="text-sm text-slate-300">{confirm.body}</p>
          <div className="mt-4 flex gap-2">
            <Button variant="danger" onClick={() => { const c = confirm; setConfirm(null); void c.run() }}>Confirm</Button>
            <Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button>
          </div>
        </Modal>
      )}
    </div>
  )
}
