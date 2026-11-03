import { useCallback, useEffect, useState } from 'react'
import { governanceApi } from '../api/governance'
import { useAuth } from '../context/auth'
import type { AuditRecord, User } from '../types/api'
import type { RoleMatrix } from '../types/governance'
import { DataTable } from '../components/tables/DataTable'
import { Button, Card, ErrorState, Field, Modal, PageHeader, Spinner, StatusPill, Tabs, inputClass } from '../components/ui/Primitives'

const ROLES = ['administrator', 'analyst', 'investigator', 'viewer']

/** Access administration. All checks are enforced by the backend; this page only reflects them. */
export function AccessAdminPage() {
  const { user: me } = useAuth()
  const [tab, setTab] = useState('users')
  const [users, setUsers] = useState<User[] | null>(null)
  const [matrix, setMatrix] = useState<RoleMatrix | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [history, setHistory] = useState<{ user: User; rows: AuditRecord[] } | null>(null)
  const [resetFor, setResetFor] = useState<User | null>(null)
  const [newPassword, setNewPassword] = useState('')

  const load = useCallback(() => {
    governanceApi.users().then(setUsers).catch((e) => setError(e.message))
    governanceApi.roles().then(setMatrix).catch((e) => setError(e.message))
  }, [])
  useEffect(load, [load])

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setError(null); setNotice(null)
    try { await fn(); setNotice(ok); load() } catch (e) { setError((e as Error).message) }
  }

  return (
    <div>
      <PageHeader
        title="Access Administration"
        description="Accounts and roles for your organization. Role changes, disabling an account, password resets and 'revoke sessions' invalidate that user's existing sessions. Safety rules (no self-demotion, never remove the last administrator) are enforced by the server."
      />
      {error && <ErrorState message={error} />}
      {notice && <div className="mb-3 rounded-md border border-status-good/40 bg-status-good/10 px-3 py-2 text-sm text-status-good">{notice}</div>}
      <Tabs tabs={[{ key: 'users', label: 'Users' }, { key: 'roles', label: 'Roles & permissions' }]} active={tab} onChange={setTab} />
      {!users && !error && <Spinner />}
      {tab === 'users' && users && (
        <DataTable
          rows={users}
          columns={[
            { header: 'User', render: (u) => <div><div className="text-slate-100">{u.display_name}</div><div className="text-xs text-slate-500">{u.username} · {u.email}</div></div> },
            {
              header: 'Role',
              render: (u) => (
                <select className={inputClass} value={u.role} disabled={u.id === me?.id}
                  onChange={(e) => act(() => governanceApi.updateUser(u.id, { role: e.target.value }), `Role updated for ${u.username}; their sessions were revoked.`)}>
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              ),
            },
            { header: 'Status', render: (u) => <StatusPill status={u.is_active ? 'active' : 'disabled'} /> },
            { header: 'Last sign-in', render: (u) => (u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'never') },
            {
              header: 'Actions',
              render: (u) => (
                <div className="flex flex-wrap gap-1.5">
                  {u.id !== me?.id && (
                    <Button variant={u.is_active ? 'danger' : 'secondary'}
                      onClick={() => act(() => governanceApi.updateUser(u.id, { is_active: !u.is_active }), `${u.username} ${u.is_active ? 'disabled' : 'enabled'}.`)}>
                      {u.is_active ? 'Disable' : 'Enable'}
                    </Button>
                  )}
                  <Button variant="secondary" onClick={() => act(() => governanceApi.revokeUserSessions(u.id), `Sessions revoked for ${u.username}.`)}>Revoke sessions</Button>
                  <Button variant="secondary" onClick={() => { setResetFor(u); setNewPassword('') }}>Reset password</Button>
                  <Button variant="secondary" onClick={() => governanceApi.accessHistory(u.id).then((rows) => setHistory({ user: u, rows })).catch((e) => setError(e.message))}>History</Button>
                </div>
              ),
            },
          ]}
        />
      )}
      {tab === 'roles' && matrix && (
        <div className="grid gap-4 md:grid-cols-2">
          {matrix.roles.map((r) => (
            <Card key={r.role}>
              <div className="mb-2 flex items-center justify-between"><span className="font-semibold capitalize text-slate-100">{r.role}</span><span className="text-xs text-slate-500">{r.permission_count} permissions</span></div>
              <div className="flex max-h-56 flex-wrap gap-1 overflow-y-auto">
                {r.permissions.map((p) => <span key={p} className="rounded-sm bg-charcoal-700 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">{p}</span>)}
              </div>
            </Card>
          ))}
          <p className="text-xs text-slate-500 md:col-span-2">The role→permission matrix is defined in code and read-only here. Roles are not custom-editable.</p>
        </div>
      )}
      {history && (
        <Modal title={`Access history — ${history.user.username}`} onClose={() => setHistory(null)}>
          {history.rows.length === 0 ? <div className="text-sm text-slate-500">No recorded account changes.</div> : (
            <ul className="space-y-2 text-xs text-slate-300">
              {history.rows.map((r) => (
                <li key={r.id} className="rounded-sm border border-charcoal-600 p-2">
                  <div>{new Date(r.created_at).toLocaleString()} — <span className="font-mono">{r.action}</span> <StatusPill status={r.outcome} /></div>
                  <div className="text-slate-500">by {r.actor_user_id?.slice(0, 8) ?? 'system'}</div>
                  {(r.context_metadata as { before?: unknown }).before !== undefined && (
                    <div className="font-mono">{JSON.stringify((r.context_metadata as { before?: unknown }).before)} → {JSON.stringify((r.context_metadata as { after?: unknown }).after)}</div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Modal>
      )}
      {resetFor && (
        <Modal title={`Reset password — ${resetFor.username}`} onClose={() => setResetFor(null)}>
          <Field label="New password (min length per server policy; never shown again)">
            <input type="password" autoComplete="new-password" className={inputClass} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
          </Field>
          <p className="mt-2 text-xs text-slate-500">All of this user's sessions are revoked. Share the password through a separate secure channel.</p>
          <div className="mt-3 flex gap-2">
            <Button disabled={!newPassword} onClick={() => act(() => governanceApi.resetPassword(resetFor.id, newPassword), `Password reset for ${resetFor.username}.`).then(() => setResetFor(null))}>Reset</Button>
            <Button variant="secondary" onClick={() => setResetFor(null)}>Cancel</Button>
          </div>
        </Modal>
      )}
    </div>
  )
}
