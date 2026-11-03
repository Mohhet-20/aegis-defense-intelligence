import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { GeoRecordType, LocationQualityRecord, LocationQualitySummary } from '../../types/api'
import { EmptyState, ErrorState, Field, PageHeader, Spinner, StatTile, inputClass } from '../../components/ui/Primitives'
import { DataTable } from '../../components/tables/DataTable'

const RECORD_TYPES: GeoRecordType[] = ['event', 'sensor', 'observation', 'asset']

export function LocationQualityCenterPage() {
  const [recordTypes, setRecordTypes] = useState<GeoRecordType[]>(RECORD_TYPES)
  const [onlyIssues, setOnlyIssues] = useState(true)
  const [summary, setSummary] = useState<LocationQualitySummary | null>(null)
  const [issues, setIssues] = useState<LocationQualityRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  function load() {
    setError(null)
    Promise.all([
      api.geospatial.qualitySummary(recordTypes),
      api.geospatial.qualityIssues({ record_types: recordTypes, only_issues: onlyIssues, limit: 200 }),
    ])
      .then(([s, i]) => {
        setSummary(s)
        setIssues(i)
      })
      .catch((e) => setError(e.message))
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [onlyIssues])

  function toggleType(t: GeoRecordType) {
    setRecordTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  }

  return (
    <div>
      <PageHeader
        title="Location Quality Center"
        description="Every finding here comes from app/geo/validation.py's real classification of each record's own stored coordinates -- missing is never confused with invalid, and a present-but-stale or uncertainty-unknown location is reported as informational, not an error."
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
        <Field label="Scope">
          <select className={inputClass} value={onlyIssues ? 'issues' : 'all'} onChange={(e) => setOnlyIssues(e.target.value === 'issues')}>
            <option value="issues">Issues only</option>
            <option value="all">All located records</option>
          </select>
        </Field>
        <button onClick={load} className="rounded-md bg-accent-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-400">
          Refresh
        </button>
      </div>

      {error && <ErrorState message={error} />}
      {!summary && !error && <Spinner />}

      {summary && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-7">
            <StatTile label="Checked" value={summary.total_records_checked} />
            <StatTile label="Valid" value={summary.valid_count} />
            <StatTile label="Missing" value={summary.missing_count} />
            <StatTile label="Invalid range" value={summary.invalid_range_count} />
            <StatTile label="Non-finite" value={summary.non_finite_count} />
            <StatTile label="Unsupported CRS" value={summary.unsupported_crs_count} />
            <StatTile label="Stale" value={summary.stale_count} />
          </div>

          {issues && issues.length === 0 && <EmptyState message="No matching records." />}
          {issues && issues.length > 0 && (
            <DataTable
              rows={issues.map((r) => ({ ...r, id: `${r.record_type}-${r.record_id}` }))}
              columns={[
                { header: 'Type', render: (r) => <span className="text-xs capitalize text-slate-400">{r.record_type}</span> },
                { header: 'Title', render: (r) => <span className="text-slate-200">{r.title}</span> },
                {
                  header: 'Coordinates',
                  render: (r) => (
                    <span className="font-mono text-xs">
                      {r.latitude !== null && r.longitude !== null ? `${r.latitude.toFixed(4)}, ${r.longitude.toFixed(4)} (${r.coordinate_reference_system})` : '--'}
                    </span>
                  ),
                },
                { header: 'Status', render: (r) => <span className="text-xs">{r.location_validation_status ?? 'missing'}</span> },
                {
                  header: 'Findings',
                  render: (r) => (
                    <ul className="space-y-0.5">
                      {r.findings.map((f) => (
                        <li key={f.code} className={`text-xs ${f.is_error ? 'text-status-critical' : 'text-status-warning'}`} title={f.explanation}>
                          {f.code.replace(/_/g, ' ')}
                        </li>
                      ))}
                    </ul>
                  ),
                },
              ]}
            />
          )}
        </>
      )}
    </div>
  )
}
