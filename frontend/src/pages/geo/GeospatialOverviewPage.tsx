import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { GeospatialOverview } from '../../types/api'
import { Card, DataOriginBadge, EmptyState, ErrorState, PageHeader, Spinner, StatTile } from '../../components/ui/Primitives'

export function GeospatialOverviewPage() {
  const [overview, setOverview] = useState<GeospatialOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.geospatial
      .overview()
      .then((d) => !cancelled && setOverview(d))
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div>
      <PageHeader
        title="Geospatial Intelligence Overview"
        description="A summary of located records, data quality, and pending spatial-relationship review across the Geospatial Intelligence Workspace. Counts here are over this project's own stored data only -- never a live feed, and never a basis for a threat conclusion."
      />

      {error && <ErrorState message={error} />}
      {!overview && !error && <Spinner />}

      {overview && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatTile label="Located records" value={overview.located_records_total} hint="valid, mappable coordinates" />
            <StatTile label="Missing / invalid locations" value={overview.missing_or_invalid_location_total} hint="present-but-unusable coordinates" />
            <StatTile label="Spatial relationship candidates" value={overview.spatial_relationship_candidates_unreviewed} hint="awaiting review" />
            <StatTile label="Location conflicts" value={overview.location_conflicts_unreviewed} hint="unresolved, from fusion" />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Card>
              <h3 className="mb-3 text-sm font-semibold text-slate-200">Located records by type</h3>
              <ul className="space-y-1 text-sm">
                {Object.entries(overview.located_records_by_type).map(([type, count]) => (
                  <li key={type} className="flex justify-between border-b border-charcoal-700/50 py-1 last:border-0">
                    <span className="capitalize text-slate-400">{type}</span>
                    <span className="font-mono text-slate-200">{count}</span>
                  </li>
                ))}
              </ul>
            </Card>
            <Card>
              <h3 className="mb-3 text-sm font-semibold text-slate-200">Temporal coverage</h3>
              <p className="text-sm text-slate-400">
                Earliest: <span className="font-mono text-slate-200">{overview.temporal_coverage_earliest ? new Date(overview.temporal_coverage_earliest).toLocaleString() : 'n/a'}</span>
              </p>
              <p className="mt-1 text-sm text-slate-400">
                Latest: <span className="font-mono text-slate-200">{overview.temporal_coverage_latest ? new Date(overview.temporal_coverage_latest).toLocaleString() : 'n/a'}</span>
              </p>
              <p className="mt-3 text-xs text-slate-500">
                Data quality: {overview.data_quality_summary.valid_count} valid, {overview.data_quality_summary.missing_count} missing,{' '}
                {overview.data_quality_summary.invalid_range_count + overview.data_quality_summary.non_finite_count + overview.data_quality_summary.unsupported_crs_count} invalid.{' '}
                <Link to="/geospatial/quality" className="text-accent-400 hover:underline">
                  View Location Quality Center
                </Link>
              </p>
            </Card>
          </div>

          <Card>
            <h3 className="mb-3 text-sm font-semibold text-slate-200">Recently located records</h3>
            {overview.recent_located_records.length === 0 && <EmptyState message="No located records yet." />}
            {overview.recent_located_records.length > 0 && (
              <ul className="divide-y divide-charcoal-700/50">
                {overview.recent_located_records.map((r) => (
                  <li key={`${r.record_type}-${r.record_id}`} className="flex items-center justify-between py-2 text-sm">
                    <div>
                      <span className="mr-2 rounded-sm bg-charcoal-700 px-1.5 py-0.5 text-xs capitalize text-slate-400">{r.record_type}</span>
                      <span className="text-slate-200">{r.title}</span>
                      {r.is_synthetic && <span className="ml-2"><DataOriginBadge origin="synthetic_demo" /></span>}
                    </div>
                    <div className="text-right text-xs text-slate-500">
                      <div>{r.latitude.toFixed(4)}, {r.longitude.toFixed(4)}</div>
                      <div>{new Date(r.timestamp).toLocaleString()}</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </div>
  )
}
