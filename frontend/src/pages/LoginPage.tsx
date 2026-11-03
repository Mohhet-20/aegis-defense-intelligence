import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/auth'
import { api, ApiError, type DemoInfo } from '../api/client'
import { Button, inputClass } from '../components/ui/Primitives'

export function LoginPage() {
  const { user, login, loading } = useAuth()
  const navigate = useNavigate()
  const [usernameOrEmail, setUsernameOrEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [demo, setDemo] = useState<DemoInfo | null>(null)

  useEffect(() => {
    let active = true
    api.auth.demo().then((info) => { if (active) setDemo(info) }).catch(() => undefined)
    return () => { active = false }
  }, [])

  if (!loading && user) return <Navigate to="/" replace />

  async function signIn(identifier: string, secret: string) {
    setError(null)
    setSubmitting(true)
    try {
      await login(identifier, secret)
      navigate('/')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to sign in right now.')
    } finally {
      setSubmitting(false)
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    void signIn(usernameOrEmail, password)
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-navy-950 px-4">
      <div className="w-full max-w-sm py-8">
        <div className="mb-6 flex items-center justify-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-sm bg-accent-500 text-sm font-bold text-white">
            AE
          </div>
          <div className="text-lg font-semibold text-slate-100">AEGIS</div>
        </div>
        <div className="rounded-lg border border-charcoal-600/60 bg-charcoal-800/60 p-6 shadow-lg">
          <h1 className="mb-1 text-base font-semibold text-slate-100">Sign in</h1>
          <p className="mb-5 text-sm text-slate-400">AI Defense Intelligence &amp; Situational Awareness Platform</p>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-400">Username or email</label>
              <input
                className={inputClass}
                value={usernameOrEmail}
                onChange={(e) => setUsernameOrEmail(e.target.value)}
                autoFocus
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-400">Password</label>
              <input
                type="password"
                className={inputClass}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error && <div className="rounded-md border border-status-critical/30 bg-status-critical/10 px-3 py-2 text-xs text-status-critical">{error}</div>}
            <Button type="submit" disabled={submitting}>
              {submitting ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>
          {demo?.enabled && demo.accounts && demo.password ? (
            <DemoAccounts demo={demo} disabled={submitting} onPick={(name) => void signIn(name, demo.password!)} />
          ) : import.meta.env.DEV ? (
            <p className="mt-5 text-center text-[11px] text-slate-500">
              Development accounts (from scripts/seed.py): admin / analyst / investigator / viewer
            </p>
          ) : null}
        </div>
      </div>
    </div>
  )
}

const ROLE_HINTS: Record<string, string> = {
  administrator: 'Everything, including users and security settings',
  analyst: 'Ingest data, review detections, write assessments',
  investigator: 'Run cases: evidence, timelines, notes',
  viewer: 'Read-only',
}

function DemoAccounts({ demo, disabled, onPick }: { demo: DemoInfo; disabled: boolean; onPick: (username: string) => void }) {
  return (
    <div className="mt-6 border-t border-charcoal-600/60 pt-5">
      <h2 className="text-sm font-semibold text-slate-100">Public demo -- sign in with one click</h2>
      <p className="mt-1 text-xs text-slate-400">
        Synthetic data only{demo.reset_hours ? `; everything resets every ${demo.reset_hours} h` : ''}. Shared accounts
        cannot be locked or changed.
      </p>
      <ul className="mt-3 space-y-2">
        {demo.accounts!.map((a) => (
          <li key={a.username}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(a.username)}
              className="w-full rounded-md border border-charcoal-600/60 bg-navy-950/60 px-3 py-2 text-left transition hover:border-accent-500/60 hover:bg-charcoal-700/60 disabled:opacity-50"
            >
              <span className="block text-sm font-medium capitalize text-slate-100">{a.role}</span>
              <span className="block text-[11px] text-slate-400">{ROLE_HINTS[a.role] ?? ''}</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[11px] text-slate-500">
        Or type a username above ({demo.accounts!.map((a) => a.username).join(', ')}) with password{' '}
        <code className="text-slate-400">{demo.password}</code>.
      </p>
    </div>
  )
}
