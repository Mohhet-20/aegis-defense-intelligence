import { useEffect, useState } from 'react'
import { reportingApi } from '../../api/reporting'
import type { Filters, SectionEnvelope } from '../../types/reporting'

export interface Loaded<T> { data: T | null; error: string | null; loading: boolean }

/** Loads one analytics section for the current filters; a stale response never overwrites a newer one. */
export function useSection(name: string, filters: Filters): Loaded<SectionEnvelope> {
  const [state, setState] = useState<Loaded<SectionEnvelope>>({ data: null, error: null, loading: true })
  const key = JSON.stringify(filters)
  useEffect(() => {
    let live = true
    setState((s) => ({ ...s, loading: true, error: null }))
    reportingApi.section(name, filters).then((data) => live && setState({ data, error: null, loading: false })).catch((e) => live && setState({ data: null, error: e.message ?? 'Request failed', loading: false }))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, key])
  return state
}
