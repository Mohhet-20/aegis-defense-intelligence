import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { DashboardSummary } from '../types/api'
import { useAuth } from '../context/auth'
import { visibleGroups } from '../components/layout/navigation'
import { Card, ErrorState, PageHeader, Spinner, StatTile } from '../components/ui/Primitives'

export function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { user } = useAuth()

  useEffect(() => {
    api.dashboard
      .summary()
      .then(setSummary)
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <ErrorState message={error} />
  if (!summary) return <Spinner />

  return (
    <div>
      <PageHeader
        title="Overview"
        description="Every figure below is a live aggregate query against the real database -- never a hardcoded number."
      />

      {summary.synthetic_data_present && (
        <div className="mb-5 rounded-md border border-status-warning/30 bg-status-warning/10 px-4 py-2.5 text-sm text-status-warning">
          This organization contains synthetic demonstration data (seeded for development). Look for the
          &quot;synthetic demo&quot; badge on individual records.
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatTile label="Total Events" value={summary.total_events} />
        <StatTile label="Events (24h)" value={summary.events_last_24h} />
        <StatTile label="Open Investigations" value={summary.open_investigations} />
        <StatTile label="Pending Risk Reviews" value={summary.pending_risk_reviews} />
        <StatTile label="Active Sources" value={summary.active_sources} />
        <StatTile label="Active Sensors" value={summary.active_sensors} />
        <StatTile label="Ingestion Jobs (24h)" value={summary.ingestion_jobs_last_24h} />
        <StatTile
          label="Data Mode"
          value={summary.synthetic_data_present ? 'Includes synthetic' : 'No synthetic data'}
          hint="How each record entered is shown by its data-origin badge"
        />
      </div>

      <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wide text-slate-400">Workspaces</h2>
      <p className="mb-4 max-w-3xl text-sm text-slate-500">
        Model output (detections, anomaly flags, risk scores) is advisory and always open to human review; it is never proof of intent
        on its own. Simulated and synthetic records are labelled as such.
      </p>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {visibleGroups(user?.role).map((group) => (
          <Card key={group.title}>
            <Link to={group.items[0].to} className="text-sm font-semibold text-slate-100 hover:text-accent-400">
              {group.title}
            </Link>
            <p className="mt-1 text-xs text-slate-500">{group.description}</p>
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1">
              {group.items.slice(0, 5).map((item) => (
                <Link key={item.to} to={item.to} className="text-xs text-accent-400 hover:underline">
                  {item.label}
                </Link>
              ))}
              {group.items.length > 5 && <span className="text-xs text-slate-500">+{group.items.length - 5} more in the menu</span>}
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
