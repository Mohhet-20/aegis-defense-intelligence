import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/auth'
import { api, ApiError, type DemoInfo } from '../api/client'
import { Button, inputClass } from '../components/ui/Primitives'

export function LoginPage() {
  const { user, login, exploreDemo, loading } = useAuth()
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

  async function startDemo() {
    setError(null)
    setSubmitting(true)
    try {
      await exploreDemo()
      navigate('/')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The demo is not available right now.')
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
          {demo?.enabled ? (
            <DemoAccess resetHours={demo.reset_hours ?? null} disabled={submitting} onStart={() => void startDemo()} />
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

function DemoAccess({ resetHours, disabled, onStart }: { resetHours: number | null; disabled: boolean; onStart: () => void }) {
  return (
    <section aria-label="Live demo" className="mt-6 border-t border-charcoal-600/60 pt-5">
      <h2 className="text-sm font-semibold text-slate-100">New to AEGIS?</h2>
      <p className="mt-1 text-xs text-slate-400">
        Explore the platform as a guest analyst: ingest data, run the object detector on your own photos and build
        assessments. Synthetic data only{resetHours ? `; it resets every ${resetHours} h` : ''}.
      </p>
      <button
        type="button"
        disabled={disabled}
        onClick={onStart}
        className="mt-3 w-full rounded-md border border-accent-500/60 bg-accent-500/10 px-3 py-2 text-sm font-medium text-slate-100 transition hover:bg-accent-500/20 disabled:opacity-50"
      >
        Explore the live demo
      </button>
    </section>
  )
}
