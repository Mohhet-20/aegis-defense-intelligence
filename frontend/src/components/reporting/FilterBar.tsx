import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { DataSource } from '../../types/api'
import type { Filters } from '../../types/reporting'
import { inputClass } from '../ui/Primitives'

const PRESETS = [1, 3, 7, 30, 90, 365]
const dayStr = (iso?: string) => (iso ? iso.slice(0, 10) : '')

export function FilterBar({ filters, onChange, showCategory = true }: { filters: Filters; onChange: (p: Partial<Filters>) => void; showCategory?: boolean }) {
  const [sources, setSources] = useState<DataSource[]>([])
  useEffect(() => { api.sources.list(1, 100).then((p) => setSources(p.items)).catch(() => setSources([])) }, [])
  const custom = Boolean(filters.start && filters.end)
  const setRange = (s: string, e: string) => {
    if (!s || !e) return
    const end = new Date(`${e}T00:00:00Z`)
    end.setUTCDate(end.getUTCDate() + 1) // the picked end day is inclusive; the API window end is exclusive
    onChange({ start: `${s}T00:00:00Z`, end: end.toISOString().replace('.000Z', 'Z') })
  }
  return (
    <div role="group" className="mb-4 grid gap-3 rounded-lg border border-charcoal-600/60 bg-charcoal-800/50 p-3 md:grid-cols-6" aria-label="Analytics filters">
      <label className="text-xs text-slate-400">Window
        <select className={inputClass} value={custom ? 'custom' : String(filters.days)} onChange={(e) => (e.target.value === 'custom' ? setRange(new Date(Date.now() - 6 * 864e5).toISOString().slice(0, 10), new Date().toISOString().slice(0, 10)) : onChange({ days: Number(e.target.value), start: undefined, end: undefined }))}>
          {PRESETS.map((d) => <option key={d} value={d}>Last {d} day{d > 1 ? 's' : ''}</option>)}
          <option value="custom">Custom range…</option>
        </select>
      </label>
      {custom && (
        <div className="flex gap-2 md:col-span-2">
          <label className="flex-1 text-xs text-slate-400">From (UTC day)<input type="date" className={inputClass} value={dayStr(filters.start)} onChange={(e) => setRange(e.target.value, dayStr(new Date(new Date(filters.end!).getTime() - 864e5).toISOString()))} /></label>
          <label className="flex-1 text-xs text-slate-400">To (UTC day, inclusive)<input type="date" className={inputClass} value={dayStr(new Date(new Date(filters.end!).getTime() - 864e5).toISOString())} onChange={(e) => setRange(dayStr(filters.start), e.target.value)} /></label>
        </div>
      )}
      <label className="text-xs text-slate-400">Time basis
        <select className={inputClass} value={filters.time_basis} onChange={(e) => onChange({ time_basis: e.target.value as Filters['time_basis'] })} title="Event time = when the source says it happened. Ingestion time = when AEGIS stored it.">
          <option value="event">Event time</option>
          <option value="ingestion">Ingestion time</option>
        </select>
      </label>
      <label className="text-xs text-slate-400">Interval
        <select className={inputClass} value={filters.bucket} onChange={(e) => onChange({ bucket: e.target.value as Filters['bucket'] })}>
          <option value="auto">Auto</option><option value="hour">Hourly</option><option value="day">Daily</option>
        </select>
      </label>
      <label className="text-xs text-slate-400">Source
        <select className={inputClass} value={filters.source_id} onChange={(e) => onChange({ source_id: e.target.value })}>
          <option value="">All sources</option>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </label>
      {showCategory && (
        <label className="text-xs text-slate-400">Category
          <input className={inputClass} value={filters.category} maxLength={100} placeholder="event / observation type" onChange={(e) => onChange({ category: e.target.value })} />
        </label>
      )}
      <label className="flex items-end gap-2 pb-1.5 text-xs text-slate-400"><input type="checkbox" checked={filters.include_archived} onChange={(e) => onChange({ include_archived: e.target.checked })} />Include archived</label>
    </div>
  )
}
