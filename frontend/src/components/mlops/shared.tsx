import type { ReactNode } from 'react'
import type { MetricValue } from '../../types/mlops'

/** Shows a metric exactly as measured. An undefined metric is "undefined" with its reason -- never 0. */
export function MetricCell({ metric }: { metric: MetricValue | undefined }) {
  if (!metric) return <span className="text-slate-500">not computed</span>
  if (!metric.defined || metric.value === null) {
    return <span className="text-slate-500" title={metric.reason ?? 'undefined for this data'}>undefined{metric.reason ? ` — ${metric.reason}` : ''}</span>
  }
  return (
    <span className="tabular-nums text-slate-100">
      {metric.value.toFixed(4)}
      {metric.ci95 && <span className="ml-1 text-xs text-slate-500">95% CI {metric.ci95[0].toFixed(3)}–{metric.ci95[1].toFixed(3)}</span>}
      {metric.n != null && <span className="ml-1 text-xs text-slate-500">n={metric.n}</span>}
    </span>
  )
}

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'warning'; children: ReactNode }) {
  const style = tone === 'warning' ? 'border-status-warning/40 bg-status-warning/10 text-status-warning' : 'border-charcoal-600 bg-charcoal-800/60 text-slate-400'
  return <div className={`mb-3 rounded-md border px-3 py-2 text-xs ${style}`}>{children}</div>
}
