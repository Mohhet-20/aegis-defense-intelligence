import type { ReactNode } from 'react'
import { useAuth } from '../context/auth'

// UX only: administrator pages show a clear notice instead of a form whose
// every request would be refused. The backend enforces the permission either way.
export function AdminOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  if (user?.role === 'administrator') return <>{children}</>
  return (
    <div className="max-w-xl rounded-lg border border-charcoal-700/60 bg-navy-900 p-6">
      <h1 className="text-lg font-semibold text-slate-100">Administrators only</h1>
      <p className="mt-2 text-sm text-slate-400">
        This page manages accounts, audit records or security settings. Your role ({user?.role ?? 'unknown'}) does not include
        that permission. Ask an administrator if you need access.
      </p>
    </div>
  )
}
