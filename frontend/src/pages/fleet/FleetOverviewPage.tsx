import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { FleetOverview } from '../../types/api'
import { Card, EmptyState, ErrorState, PageHeader, Spinner, StatTile, StatusPill } from '../../components/ui/Primitives'

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString()
}

function formatPct(value: number | null): string {
  // overview.baseline_assignment_pct is already a 0-100 percentage
  // (see app/services/fleet_analytics_service.py), not a 0-1 fraction --
  // do not multiply by 100 again here.
  if (value === null) return 'No baseline data'
  return `${value.toFixed(1)}%`
}

export function FleetOverviewPage() {
  const [overview, setOverview] = useState<FleetOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.fleetAnalytics
      .overview()
      .then((o) => {
        setOverview(o)
        setError(null)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load fleet overview.'))
  }, [])

  if (error) return <ErrorState message={error} />
  if (!overview) return <Spinner />

  const presenceEntries = Object.entries(overview.presence_counts)
  const adminEntries = Object.entries(overview.administrative_status_counts)
  const severityEntries = Object.entries(overview.open_alerts_by_severity)

  return (
    <div>
      <PageHeader
        title="Fleet Overview"
        description={`A single point-in-time snapshot of the edge device fleet as of ${formatDateTime(overview.as_of)} -- this is not a trend, there is only one data point here.`}
      />

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatTile label="Total devices" value={overview.total_devices} />
        <StatTile
          label="Baseline assignment"
          value={formatPct(overview.baseline_assignment_pct)}
          hint={`${overview.devices_with_assigned_baseline} of ${overview.total_devices} devices have an assigned config baseline`}
        />
        <StatTile
          label="Unresolved sync conflicts"
          value={
            <Link to="/edge/conflicts" className="text-accent-400 hover:underline">
              {overview.unresolved_sync_conflicts}
            </Link>
          }
        />
        <StatTile label="Total open alerts" value={overview.total_open_alerts} />
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Presence (server-authoritative)</h2>
          {presenceEntries.length === 0 ? (
            <EmptyState message="No devices registered yet." />
          ) : (
            <div className="flex flex-col gap-2">
              {presenceEntries.map(([state, count]) => (
                <Link
                  key={state}
                  to={`/edge/devices?presence_state=${encodeURIComponent(state)}`}
                  className="flex items-center justify-between rounded-md border border-charcoal-700/60 px-3 py-2 hover:bg-charcoal-700/40"
                >
                  <StatusPill status={state} />
                  <span className="text-sm font-medium text-slate-200">{count}</span>
                </Link>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Administrative status</h2>
          {adminEntries.length === 0 ? (
            <EmptyState message="No devices registered yet." />
          ) : (
            <div className="flex flex-col gap-2">
              {adminEntries.map(([status, count]) => (
                <Link
                  key={status}
                  to={`/edge/devices?administrative_status=${encodeURIComponent(status)}`}
                  className="flex items-center justify-between rounded-md border border-charcoal-700/60 px-3 py-2 hover:bg-charcoal-700/40"
                >
                  <StatusPill status={status} />
                  <span className="text-sm font-medium text-slate-200">{count}</span>
                </Link>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Open alerts by severity</h2>
          {severityEntries.length === 0 ? (
            <EmptyState message="No open infrastructure alerts." />
          ) : (
            <div className="flex flex-col gap-2">
              {severityEntries.map(([severity, count]) => (
                <Link
                  key={severity}
                  to={`/fleet/alerts?severity=${encodeURIComponent(severity)}`}
                  className="flex items-center justify-between rounded-md border border-charcoal-700/60 px-3 py-2 hover:bg-charcoal-700/40"
                >
                  <StatusPill status={severity} />
                  <span className="text-sm font-medium text-slate-200">{count}</span>
                </Link>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
