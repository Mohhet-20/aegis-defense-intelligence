import { useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import type { WorkspaceInvestigation } from '../../types/workspace'
import { Button, Card, EmptyState, ErrorState, Field, StatusPill, inputClass } from '../ui/Primitives'
import { LoadState, Mono, Notice } from './InvestigationBits'
import { fmtTime, useLoad, errorText } from './useLoad'

const NEXT: Record<string, string[]> = {
  draft: ['open'],
  open: ['active', 'pending_review', 'closed'],
  active: ['open', 'pending_review', 'closed'],
  pending_review: ['active', 'closed'],
  closed: ['open', 'archived'],
  archived: [],
}
const LINK_TYPES = ['event', 'observation', 'assessment', 'data_source', 'sensor', 'media_asset', 'detection_result', 'track']

export function OverviewTab({ inv, canWrite, onChanged }: { inv: WorkspaceInvestigation; canWrite: boolean; onChanged: () => void }) {
  const history = useLoad(() => api.workspace.statusHistory(inv.id), [inv.id, inv.status])
  const members = useLoad(() => api.workspace.members(inv.id), [inv.id])
  const links = useLoad(() => api.workspace.links(inv.id), [inv.id])
  const users = useLoad(() => api.users.list(), [])
  const audit = useLoad(() => api.workspace.audit(inv.id), [inv.id, inv.status])
  const [error, setError] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [memberId, setMemberId] = useState('')
  const [memberRole, setMemberRole] = useState('reviewer')
  const [linkType, setLinkType] = useState('event')
  const [linkId, setLinkId] = useState('')
  const [exporting, setExporting] = useState(false)
  const [includeMedia, setIncludeMedia] = useState(false)
  const readOnly = inv.status === 'archived'
  const editable = canWrite && !readOnly
  const name = (id: string | null) => (id ? (users.data?.find((u) => u.id === id)?.display_name ?? id) : 'Unassigned')

  async function act(fn: () => Promise<unknown>, after?: () => void) {
    setError(null)
    try { await fn(); after?.() } catch (e) { setError(errorText(e, 'Action failed.')) }
  }
  const move = (to: string) => act(() => api.workspace.transition(inv.id, to, reason || undefined), () => { setReason(''); onChanged() })
  const addMember = (e: FormEvent) => { e.preventDefault(); void act(() => api.workspace.addMember(inv.id, memberId, memberRole), () => { setMemberId(''); members.reload() }) }
  const addLink = (e: FormEvent) => { e.preventDefault(); void act(() => api.workspace.addLink(inv.id, linkType, linkId.trim()), () => { setLinkId(''); links.reload() }) }

  async function exportReport(format: 'json' | 'zip') {
    setExporting(true)
    await act(() => api.workspace.exportReport(inv.id, format, format === 'zip' && includeMedia))
    setExporting(false)
    audit.reload()
  }

  return (
    <div className="space-y-4">
      {error && <ErrorState message={error} />}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Overview</h2>
          <div className="flex flex-wrap gap-2"><StatusPill status={inv.status} /><StatusPill status={inv.priority} /><StatusPill status={inv.review_status} />{inv.is_restricted && <span className="rounded-full border border-status-warning/30 px-2 text-xs text-status-warning">restricted access</span>}</div>
          <p className="mt-3 text-sm text-slate-300">{inv.description ?? 'No description provided.'}</p>
          {inv.purpose && <p className="mt-2 text-sm text-slate-400"><span className="text-slate-500">Purpose: </span>{inv.purpose}</p>}
          {inv.tags.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{inv.tags.map((t) => <span key={t} className="rounded-sm bg-charcoal-700 px-1.5 text-xs text-slate-300">{t}</span>)}</div>}
          <dl className="mt-3 space-y-1 text-xs text-slate-400">
            <div>Owner: {name(inv.assigned_user_id)}</div>
            <div>Created: {fmtTime(inv.created_at)}</div>
            <div>Last modified: {fmtTime(inv.updated_at)}</div>
            {inv.closed_at && <div>Closed: {fmtTime(inv.closed_at)} -- {inv.closure_reason}</div>}
            {inv.archived_at && <div>Archived: {fmtTime(inv.archived_at)}</div>}
          </dl>
          {inv.resolution_notes && <p className="mt-2 text-sm text-slate-300"><span className="text-slate-500">Resolution notes: </span>{inv.resolution_notes}</p>}
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Status transitions</h2>
          {readOnly ? <p className="text-sm text-slate-500">Archived investigations are read-only.</p> : editable ? (
            <>
              <Field label="Reason (required when closing)"><input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} /></Field>
              <div className="mt-3 flex flex-wrap gap-2">{(NEXT[inv.status] ?? []).map((s) => <Button key={s} variant={s === 'closed' ? 'danger' : 'secondary'} onClick={() => move(s)}>{inv.status === 'closed' && s === 'open' ? 'Reopen' : `Move to ${s.replace('_', ' ')}`}</Button>)}</div>
            </>
          ) : <p className="text-sm text-slate-500">Your role cannot change status.</p>}
          <h3 className="mb-1 mt-4 text-xs uppercase tracking-wide text-slate-500">History</h3>
          <LoadState loading={history.loading} error={history.error}>
            <ol className="space-y-1 text-xs text-slate-400">{(history.data ?? []).map((h) => <li key={h.id}>{fmtTime(h.created_at)} -- {h.from_status ?? '(new)'} → {h.to_status}{h.reason ? ` (${h.reason})` : ''}</li>)}</ol>
          </LoadState>
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Team</h2>
          <LoadState loading={members.loading} error={members.error}>
            {members.data && members.data.length === 0 ? <p className="text-sm text-slate-500">No reviewers or members assigned.</p> : (
              <ul className="space-y-1 text-sm">{(members.data ?? []).map((m) => (
                <li key={m.id} className="flex items-center justify-between"><span>{name(m.user_id)} <span className="text-xs text-slate-500">({m.role})</span></span>
                  {editable && <button className="text-xs text-status-danger hover:underline" onClick={() => act(() => api.workspace.removeMember(inv.id, m.user_id), members.reload)}>Remove</button>}</li>
              ))}</ul>
            )}
          </LoadState>
          {editable && (
            <form onSubmit={addMember} className="mt-3 flex flex-wrap items-end gap-2">
              <Field label="User"><select className={inputClass} value={memberId} onChange={(e) => setMemberId(e.target.value)} required><option value="">Select…</option>{(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.display_name} ({u.role})</option>)}</select></Field>
              <Field label="Role"><select className={inputClass} value={memberRole} onChange={(e) => setMemberRole(e.target.value)}><option>reviewer</option><option>member</option></select></Field>
              <Button type="submit">Add</Button>
            </form>
          )}
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Report export</h2>
          <Notice>The export is generated by this application from stored records. It is not independently authenticated or signed; its manifest hashes only let a recipient detect later changes. Generation time is not an evidence time.</Notice>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="secondary" disabled={exporting} onClick={() => exportReport('json')}>Download JSON</Button>
            <Button variant="secondary" disabled={exporting} onClick={() => exportReport('zip')}>Download ZIP</Button>
            <label className="flex items-center gap-1 text-xs text-slate-400"><input type="checkbox" checked={includeMedia} onChange={(e) => setIncludeMedia(e.target.checked)} /> include media files (ZIP)</label>
          </div>
        </Card>
      </div>

      <Card>
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Linked records</h2>
        <LoadState loading={links.loading} error={links.error}>
          {links.data && links.data.length === 0 && inv.linked_event_ids.length === 0 ? <EmptyState message="No records linked yet." /> : (
            <ul className="divide-y divide-charcoal-700 text-sm">
              {(links.data ?? []).map((l) => (
                <li key={l.id} className="flex items-center justify-between py-2">
                  <div><StatusPill status={l.record_type} /> <span className="text-slate-200">{l.summary?.title ?? (l.resolvable ? 'Restricted or unavailable' : 'Record no longer available')}</span> <Mono>{l.record_id}</Mono></div>
                  {editable && <button className="text-xs text-status-danger hover:underline" onClick={() => act(() => api.workspace.removeLink(inv.id, l.id), links.reload)}>Unlink</button>}
                </li>
              ))}
              {inv.linked_event_ids.map((id) => <li key={`legacy-${id}`} className="py-2 text-xs text-slate-500">Legacy event reference <Mono>{id}</Mono></li>)}
            </ul>
          )}
        </LoadState>
        {editable && (
          <form onSubmit={addLink} className="mt-3 flex flex-wrap items-end gap-2">
            <Field label="Type"><select className={inputClass} value={linkType} onChange={(e) => setLinkType(e.target.value)}>{LINK_TYPES.map((t) => <option key={t}>{t}</option>)}</select></Field>
            <Field label="Record id"><input className={inputClass} value={linkId} onChange={(e) => setLinkId(e.target.value)} required maxLength={36} /></Field>
            <Button type="submit">Link record</Button>
          </form>
        )}
      </Card>

      <Card>
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Audit history</h2>
        <LoadState loading={audit.loading} error={audit.error}>
          <ul className="max-h-64 space-y-1 overflow-auto text-xs text-slate-400">{(audit.data ?? []).map((a) => <li key={a.id}>{fmtTime(a.created_at)} -- {a.action} ({a.outcome}) by {name(a.actor_user_id)}</li>)}</ul>
          <p className="mt-2 text-xs text-slate-500">An application audit trail of changes made through AEGIS; not a legally certified chain of custody.</p>
        </LoadState>
      </Card>
    </div>
  )
}
