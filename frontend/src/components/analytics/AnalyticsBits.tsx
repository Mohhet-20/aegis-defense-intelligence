import type { ReactNode } from 'react'
import { ApiError } from '../../api/client'
import type { DataQualityIndicator, MetricValue } from '../../types/api'
import { Card, ErrorState } from '../ui/Primitives'
import { formatMetric } from './format'

/** Distinguishes "you may not see this" from a generic failure. */
export function ApiErrorView({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 403) {
    return (
      <div className="rounded-md border border-status-warning/30 bg-status-warning/10 px-4 py-3 text-sm text-status-warning">
        Permission denied: your role does not have access to this data.
      </div>
    )
  }
  const message = error instanceof ApiError ? error.message : error instanceof Error ? error.message : 'Request failed.'
  return <ErrorState message={message} />
}

export function SyntheticBadge({ synthetic }: { synthetic: boolean | null }) {
  if (synthetic === null) return null
  return (
    <span
      title={synthetic ? 'Synthetic dataset -- not evidence of real-world performance' : 'Caller-supplied labelled dataset'}
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${
        synthetic ? 'border-status-warning/30 bg-status-warning/10 text-status-warning' : 'border-accent-500/30 bg-accent-500/10 text-accent-400'
      }`}
    >
      {synthetic ? 'synthetic dataset' : 'supplied dataset'}
    </span>
  )
}

export function MetricCard({ label, metric }: { label: string; metric: MetricValue }) {
  return (
    <Card>
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${metric.defined ? 'text-slate-100' : 'text-slate-500'}`}>{formatMetric(metric)}</div>
      {!metric.defined && metric.reason && <div className="mt-1 text-xs text-status-warning">Undefined: {metric.reason}</div>}
      <p className="mt-2 text-xs leading-relaxed text-slate-500">{metric.definition}</p>
    </Card>
  )
}

const SEVERITY_STYLE: Record<string, string> = {
  info: 'border-slate-500/30 bg-slate-500/10 text-slate-300',
  warning: 'border-status-warning/30 bg-status-warning/10 text-status-warning',
  error: 'border-status-critical/30 bg-status-critical/10 text-status-critical',
}

export function DataQualityList({ items, emptyText = 'No data-quality concerns were detected.' }: { items: DataQualityIndicator[]; emptyText?: ReactNode }) {
  if (items.length === 0) return <p className="text-sm text-slate-500">{emptyText}</p>
  return (
    <ul className="space-y-1.5">
      {items.map((i) => (
        <li key={i.code} className={`rounded-md border px-3 py-2 text-sm ${SEVERITY_STYLE[i.severity]}`}>
          <span className="mr-2 text-xs font-semibold uppercase">{i.severity}</span>
          {i.message}
        </li>
      ))}
    </ul>
  )
}
