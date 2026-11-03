import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { Page, Sensor, SensorLifecycleStatus } from '../types/api'
import { useAuth } from '../context/auth'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatTile, StatusPill, inputClass } from '../components/ui/Primitives'

const LIFECYCLE_STATUSES: SensorLifecycleStatus[] = ['registered', 'active', 'degraded', 'offline', 'maintenance', 'retired']

export function SensorsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [data, setData] = useState<Page<Sensor> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [lifecycleFilter, setLifecycleFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [search, setSearch] = useState('')

  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [sensorType, setSensorType] = useState('camera')
  const [category, setCategory] = useState('')
  const [measurementType, setMeasurementType] = useState('')
  const [measurementUnit, setMeasurementUnit] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst'

  function load() {
    api.sensors
      .list({ page, page_size: 20, lifecycle_status: lifecycleFilter || undefined, category: categoryFilter || undefined, search: search || undefined })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [page, lifecycleFilter, categoryFilter, search])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    try {
      await api.sensors.create({
        name,
        sensor_type: sensorType,
        category: category || undefined,
        measurement_types: measurementType ? [measurementType] : [],
        measurement_units: measurementType && measurementUnit ? { [measurementType]: measurementUnit } : {},
      })
      setName('')
      setCategory('')
      setMeasurementType('')
      setMeasurementUnit('')
      setShowForm(false)
      load()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not register sensor.')
    }
  }

  const lifecycleCounts = (data?.items ?? []).reduce<Record<string, number>>((acc, s) => {
    acc[s.lifecycle_status] = (acc[s.lifecycle_status] ?? 0) + 1
    return acc
  }, {})

  return (
    <div>
      <PageHeader
        title="Sensor Registry"
        description="Registry and lifecycle for every configured sensor. A newly-registered sensor starts at lifecycle_status='registered' until it reports a first valid observation."
        actions={canManage && <Button onClick={() => setShowForm((s) => !s)}>{showForm ? 'Cancel' : 'Register sensor'}</Button>}
      />

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="On this page" value={data?.items.length ?? '--'} />
        <StatTile label="Active" value={lifecycleCounts.active ?? 0} hint="connected, good quality, no unresolved anomalies" />
        <StatTile label="Degraded" value={lifecycleCounts.degraded ?? 0} hint="quality or anomaly threshold breached" />
        <StatTile label="Offline / registered" value={(lifecycleCounts.offline ?? 0) + (lifecycleCounts.registered ?? 0)} hint="missed heartbeat, or never reported" />
      </div>

      {showForm && (
        <Card className="mb-5 max-w-lg">
          <form onSubmit={handleCreate} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Name">
                <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required />
              </Field>
              <Field label="Sensor type">
                <input className={inputClass} value={sensorType} onChange={(e) => setSensorType(e.target.value)} required />
              </Field>
              <Field label="Category (optional)">
                <input className={inputClass} value={category} onChange={(e) => setCategory(e.target.value)} placeholder="environmental, camera, gps..." />
              </Field>
              <Field label="Primary measurement type (optional)">
                <input className={inputClass} value={measurementType} onChange={(e) => setMeasurementType(e.target.value)} placeholder="temperature_c" />
              </Field>
              <Field label="Unit (optional)">
                <input className={inputClass} value={measurementUnit} onChange={(e) => setMeasurementUnit(e.target.value)} placeholder="celsius" />
              </Field>
            </div>
            {formError && <ErrorState message={formError} />}
            <Button type="submit">Create</Button>
          </form>
        </Card>
      )}

      <Card className="mb-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="Search (name/description)">
            <input className={inputClass} value={search} onChange={(e) => { setPage(1); setSearch(e.target.value) }} placeholder="Search sensors..." />
          </Field>
          <Field label="Lifecycle status">
            <select className={inputClass} value={lifecycleFilter} onChange={(e) => { setPage(1); setLifecycleFilter(e.target.value) }}>
              <option value="">All</option>
              {LIFECYCLE_STATUSES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </Field>
          <Field label="Category">
            <input className={inputClass} value={categoryFilter} onChange={(e) => { setPage(1); setCategoryFilter(e.target.value) }} placeholder="environmental, camera..." />
          </Field>
        </div>
      </Card>

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No sensors match these filters." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            onRowClick={(r) => navigate(`/sensors/${r.id}`)}
            columns={[
              { header: 'Name', render: (r) => <Link to={`/sensors/${r.id}`} className="font-medium text-accent-400 hover:underline" onClick={(e) => e.stopPropagation()}>{r.name}</Link> },
              { header: 'Type / category', render: (r) => <span>{r.sensor_type}{r.category ? ` / ${r.category}` : ''}</span> },
              { header: 'Legacy status', render: (r) => <StatusPill status={r.status} /> },
              { header: 'Lifecycle status', render: (r) => <StatusPill status={r.lifecycle_status} /> },
              { header: 'Measurement types', render: (r) => (r.measurement_types.length > 0 ? r.measurement_types.join(', ') : '(unconfigured)') },
              { header: 'Last seen', render: (r) => (r.last_seen_at ? new Date(r.last_seen_at).toLocaleString() : 'never') },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
