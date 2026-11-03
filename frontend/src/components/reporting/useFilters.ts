import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { Filters } from '../../types/reporting'

const DEFAULTS: Filters = { days: 7, time_basis: 'event', source_id: '', category: '', include_archived: false, bucket: 'auto' }

/** Filter state lives in the URL so every dashboard shares it, back/forward work, and drill-downs keep the window. */
export function useReportingFilters(): [Filters, (patch: Partial<Filters>) => void] {
  const [sp, setSp] = useSearchParams()
  const filters = useMemo<Filters>(() => {
    const days = Number(sp.get('days'))
    const tb = sp.get('time_basis')
    const b = sp.get('bucket')
    return {
      days: days >= 1 && days <= 366 ? days : DEFAULTS.days,
      time_basis: tb === 'ingestion' ? 'ingestion' : 'event',
      source_id: sp.get('source_id') ?? '',
      category: sp.get('category') ?? '',
      include_archived: sp.get('include_archived') === 'true',
      bucket: b === 'hour' || b === 'day' ? b : 'auto',
      start: sp.get('start') ?? undefined,
      end: sp.get('end') ?? undefined,
    }
  }, [sp])
  const update = useCallback((patch: Partial<Filters>) => {
    const next = { ...filters, ...patch }
    const s = new URLSearchParams(sp)
    const setOrDel = (k: string, v: string | number | undefined | boolean) => { if (v === undefined || v === '' || v === false) s.delete(k); else s.set(k, String(v)) }
    if (next.start && next.end) { setOrDel('start', next.start); setOrDel('end', next.end); s.delete('days') } else { s.delete('start'); s.delete('end'); setOrDel('days', next.days === DEFAULTS.days ? undefined : next.days) }
    setOrDel('time_basis', next.time_basis === 'event' ? undefined : next.time_basis)
    setOrDel('bucket', next.bucket === 'auto' ? undefined : next.bucket)
    setOrDel('source_id', next.source_id)
    setOrDel('category', next.category)
    setOrDel('include_archived', next.include_archived)
    setSp(s, { replace: false })
  }, [filters, sp, setSp])
  return [filters, update]
}
