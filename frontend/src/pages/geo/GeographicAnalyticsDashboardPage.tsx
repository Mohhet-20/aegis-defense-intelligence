import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { GeoRecordType, SpatialGridResult, TemporalGapsResult } from '../../types/api'
import { Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatTile, inputClass } from '../../components/ui/Primitives'

const RECORD_TYPES: GeoRecordType[] = ['event', 'sensor', 'observation', 'asset']

function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * 86400_000).toISOString().slice(0, 16)
}

export function GeographicAnalyticsDashboardPage() {
  const [recordTypes, setRecordTypes] = useState<GeoRecordType[]>(RECORD_TYPES)
  const [grid, setGrid] = useState<SpatialGridResult | null>(null)
  const [gapRecordType, setGapRecordType] = useState<GeoRecordType>('event')
  const [gaps, setGaps] = useState<TemporalGapsResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const since = isoDaysAgo(30)
  const until = new Date().toISOString().slice(0, 16)

  function load() {
    setError(null)
    api.geospatial
      .spatialGrid({ record_types: recordTypes, grid_resolution_degrees: 0.5 })
      .then(setGrid)
      .catch((e) => setError(e.message))
    api.geospatial
      .temporalGaps({ record_type: gapRecordType, since: new Date(since).toISOString(), until: new Date(until).toISOString(), min_gap_seconds: 3600 })
      .then(setGaps)
      .catch((e) => setError(e.message))
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [recordTypes, gapRecordType])

  function toggleType(t: GeoRecordType) {
    setRecordTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  }

  return (
    <div>
      <PageHeader
        title="Geographic Analytics Dashboard"
        description="Counts by area and gaps in reporting over this project's own stored records -- never a density-based inference about real-world activity, and never a basis for assigning a threat level to a location."
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Record types">
          <div className="flex gap-2">
            {RECORD_TYPES.map((t) => (
              <button
                key={t}
                onClick={() => toggleType(t)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium capitalize ${
                  recordTypes.includes(t) ? 'bg-accent-500/15 text-accent-400' : 'bg-charcoal-800 text-slate-400 hover:bg-charcoal-700'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </Field>
      </div>

      {error && <ErrorState message={error} />}

      <Card className="mb-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-200">
          Counts by geographic area (0.5&deg; grid) {grid?.is_approximate && <span className="text-xs text-status-warning">(bounded sample)</span>}
        </h3>
        {!grid && <Spinner />}
        {grid && grid.cells.length === 0 && <EmptyState message="No located records to grid." />}
        {grid && grid.cells.length > 0 && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {grid.cells.slice(0, 12).map((cell, i) => (
              <StatTile
                key={i}
                label={`${cell.min_lat.toFixed(2)}, ${cell.min_lon.toFixed(2)}`}
                value={cell.count}
                hint={Object.entries(cell.record_types).map(([t, c]) => `${t}: ${c}`).join(', ')}
              />
            ))}
          </div>
        )}
      </Card>

      <Card>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-200">
            Temporal gaps (last 30 days, &gt;= 1h) {gaps?.is_approximate && <span className="text-xs text-status-warning">(bounded sample)</span>}
          </h3>
          <Field label="Record type">
            <select className={inputClass} value={gapRecordType} onChange={(e) => setGapRecordType(e.target.value as GeoRecordType)}>
              {RECORD_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {!gaps && <Spinner />}
        {gaps && gaps.gaps.length === 0 && <EmptyState message="No gaps at or above the threshold -- this is an absence of a gap in THIS project's own data, not a claim nothing happened." />}
        {gaps && gaps.gaps.length > 0 && (
          <ul className="divide-y divide-charcoal-700/50 text-sm">
            {gaps.gaps.map((g, i) => (
              <li key={i} className="flex justify-between py-2">
                <span className="text-slate-300">
                  {new Date(g.gap_start).toLocaleString()} &rarr; {new Date(g.gap_end).toLocaleString()}
                </span>
                <span className="font-mono text-slate-400">{(g.gap_seconds / 3600).toFixed(1)}h</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
