import type { MetricValue } from '../../types/api'

export function formatMetric(m: MetricValue | number | null | undefined, digits = 3): string {
  if (m === null || m === undefined) return 'undefined'
  const value = typeof m === 'number' ? m : m.value
  return value === null || value === undefined ? 'undefined' : value.toFixed(digits)
}
