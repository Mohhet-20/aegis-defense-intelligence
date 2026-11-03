import type { MetricValue, WindowInfo } from '../../types/reporting'

export function fmtMetric(m: MetricValue | undefined): string {
  if (!m) return 'not available'
  if (m.value === null) return `not available${m.reason ? ` — ${m.reason.replace(/_/g, ' ')}` : ''}`
  if (typeof m.value === 'number') {
    if (m.unit === 'proportion') return `${(m.value * 100).toFixed(1)}%`
    if (m.unit === 'seconds') return m.value >= 3600 ? `${(m.value / 3600).toFixed(2)} h` : m.value >= 120 ? `${(m.value / 60).toFixed(1)} min` : `${m.value.toFixed(m.value % 1 ? 1 : 0)} s`
    return Number.isInteger(m.value) ? m.value.toLocaleString() : m.value.toFixed(2)
  }
  return String(m.value)
}

export const fmtWindow = (w: WindowInfo) => `${w.start.replace('T', ' ').slice(0, 16)} → ${w.end.replace('T', ' ').slice(0, 16)} UTC (end exclusive)`
export const fmtTime = (iso: string) => new Date(iso).toLocaleString()
export const humanize = (s: string) => s.replace(/_/g, ' ')
