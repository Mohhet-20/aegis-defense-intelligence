import type { ReactNode } from 'react'
import { ApiErrorView } from '../analytics/AnalyticsBits'
import { Spinner } from '../ui/Primitives'

export function Notice({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warn' }) {
  const cls = tone === 'warn' ? 'border-status-warning/30 bg-status-warning/10 text-status-warning' : 'border-charcoal-600 bg-charcoal-900 text-slate-400'
  return <div className={`mb-3 rounded-md border px-3 py-2 text-xs leading-relaxed ${cls}`}>{children}</div>
}

/** Standard loading / error (incl. permission-denied) wrapper. */
export function LoadState({ loading, error, children }: { loading: boolean; error: unknown; children: ReactNode }) {
  if (error) return <ApiErrorView error={error} />
  if (loading) return <Spinner />
  return <>{children}</>
}


export function Mono({ children }: { children: ReactNode }) {
  return <span className="break-all font-mono text-xs text-slate-300">{children}</span>
}

