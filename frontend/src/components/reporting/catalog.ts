import { useEffect, useState } from 'react'
import { reportingApi } from '../../api/reporting'
import type { MetricDef } from '../../types/reporting'

let cache: Promise<Record<string, MetricDef>> | null = null

/** Metric definitions are loaded once; they power every tooltip so a number's meaning is one click away. */
export function useMetricCatalog(): Record<string, MetricDef> {
  const [defs, setDefs] = useState<Record<string, MetricDef>>({})
  useEffect(() => {
    cache ??= reportingApi.metrics().then((c) => Object.fromEntries(c.metrics.map((m) => [m.id, m]))).catch(() => { cache = null; return {} })
    let live = true
    cache.then((d) => { if (live) setDefs(d) })
    return () => { live = false }
  }, [])
  return defs
}
