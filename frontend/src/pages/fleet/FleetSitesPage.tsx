import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type { FleetSite, FleetSiteSummary } from '../../types/api'
import { DataTable } from '../../components/tables/DataTable'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  PageHeader,
  Spinner,
  StatusPill,
  inputClass,
} from '../../components/ui/Primitives'

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString()
}

function NewSiteDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (site: FleetSite) => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [latitude, setLatitude] = useState('')
  const [longitude, setLongitude] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit() {
    setSubmitting(true)
    setError(null)
    try {
      const lat = latitude.trim() ? Number(latitude) : undefined
      const lon = longitude.trim() ? Number(longitude) : undefined
      if (latitude.trim() && Number.isNaN(lat)) throw new Error('Latitude must be a number.')
      if (longitude.trim() && Number.isNaN(lon)) throw new Error('Longitude must be a number.')
      const site = await api.fleetSites.create({ name, description: description || undefined, latitude: lat, longitude: lon })
      onCreated(site)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Failed to create site.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal title="New site" onClose={onClose}>
      <div className="grid gap-3">
        <Field label="Name">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} maxLength={200} placeholder="e.g. Forward Operating Base Alpha" />
        </Field>
        <Field label="Description (optional)">
          <input className={inputClass} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Latitude (optional)">
            <input className={inputClass} value={latitude} onChange={(e) => setLatitude(e.target.value)} placeholder="e.g. 17.3850" />
          </Field>
          <Field label="Longitude (optional)">
            <input className={inputClass} value={longitude} onChange={(e) => setLongitude(e.target.value)} placeholder="e.g. 78.4867" />
          </Field>
        </div>
      </div>
      {error && <div className="mt-3"><ErrorState message={error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={handleSubmit} disabled={submitting || !name.trim()}>
          {submitting ? 'Creating…' : 'Create site'}
        </Button>
      </div>
    </Modal>
  )
}

function SiteSummaryPanel({ site }: { site: FleetSite }) {
  const [summary, setSummary] = useState<FleetSiteSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setSummary(null)
    setError(null)
    api.fleetSites
      .summary(site.id)
      .then(setSummary)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load site summary.'))
  }, [site.id])

  return (
    <Card className="mt-4">
      <h2 className="mb-3 text-sm font-semibold text-slate-200">
        {site.name} -- summary
      </h2>
      {error && <ErrorState message={error} />}
      {!summary && !error && <Spinner />}
      {summary && (
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Devices</div>
            <div className="text-xl font-semibold text-slate-100">{summary.device_count}</div>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Open alerts</div>
            <div className="text-xl font-semibold text-slate-100">{summary.open_alert_count}</div>
          </div>
          <div>
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Presence</div>
            {Object.keys(summary.presence_counts).length === 0 ? (
              <span className="text-xs text-slate-500">No devices at this site.</span>
            ) : (
              <div className="flex flex-wrap gap-2">
                {Object.entries(summary.presence_counts).map(([state, count]) => (
                  <span key={state} className="flex items-center gap-1">
                    <StatusPill status={state} /> <span className="text-xs text-slate-400">{count}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="md:col-span-3">
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Administrative status</div>
            {Object.keys(summary.administrative_status_counts).length === 0 ? (
              <span className="text-xs text-slate-500">No devices at this site.</span>
            ) : (
              <div className="flex flex-wrap gap-2">
                {Object.entries(summary.administrative_status_counts).map(([s, count]) => (
                  <span key={s} className="flex items-center gap-1">
                    <StatusPill status={s} /> <span className="text-xs text-slate-400">{count}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  )
}

export function FleetSitesPage() {
  const { user } = useAuth()
  const [sites, setSites] = useState<FleetSite[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showNew, setShowNew] = useState(false)
  const [selectedSite, setSelectedSite] = useState<FleetSite | null>(null)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst'

  function load() {
    api.fleetSites
      .list()
      .then((rows) => {
        setSites(rows)
        setError(null)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load fleet sites.'))
  }

  useEffect(load, [])

  return (
    <div>
      <PageHeader
        title="Fleet Sites"
        description="Named deployment locations/groups that edge devices can be assigned to, for fleet-wide rollups by location."
        actions={canManage && <Button onClick={() => setShowNew(true)}>New site</Button>}
      />

      {error && <ErrorState message={error} />}
      {!sites && !error && <Spinner />}
      {sites && sites.length === 0 && <EmptyState message="No fleet sites created yet." />}
      {sites && sites.length > 0 && (
        <DataTable
          rows={sites}
          onRowClick={(row) => setSelectedSite(row)}
          columns={[
            { header: 'Name', render: (s) => s.name },
            { header: 'Description', render: (s) => s.description ?? '--' },
            { header: 'Latitude', render: (s) => (s.latitude !== null ? s.latitude.toFixed(5) : '--') },
            { header: 'Longitude', render: (s) => (s.longitude !== null ? s.longitude.toFixed(5) : '--') },
            { header: 'Created', render: (s) => formatDateTime(s.created_at) },
          ]}
        />
      )}

      {selectedSite && <SiteSummaryPanel site={selectedSite} />}

      {showNew && (
        <NewSiteDialog
          onClose={() => setShowNew(false)}
          onCreated={(site) => {
            load()
            setSelectedSite(site)
          }}
        />
      )}
    </div>
  )
}
