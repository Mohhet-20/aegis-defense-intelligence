import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { Asset, Page } from '../types/api'
import { useAuth } from '../context/auth'
import { DataTable } from '../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

export function AssetsPage() {
  const { user } = useAuth()
  const [data, setData] = useState<Page<Asset> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [entityType, setEntityType] = useState('facility')
  const [formError, setFormError] = useState<string | null>(null)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst'

  function load() {
    api.assets
      .list()
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    try {
      await api.assets.create({ name, entity_type: entityType })
      setName('')
      setShowForm(false)
      load()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not create asset.')
    }
  }

  return (
    <div>
      <PageHeader
        title="Asset Registry"
        description="Tracked entities (facilities, vehicles, equipment). A missing coordinate stays missing -- never defaulted to 0,0."
        actions={canManage && <Button onClick={() => setShowForm((s) => !s)}>{showForm ? 'Cancel' : 'Register asset'}</Button>}
      />

      {showForm && (
        <Card className="mb-5 max-w-md">
          <form onSubmit={handleCreate} className="space-y-3">
            <Field label="Name">
              <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field label="Entity type">
              <input className={inputClass} value={entityType} onChange={(e) => setEntityType(e.target.value)} required />
            </Field>
            {formError && <ErrorState message={formError} />}
            <Button type="submit">Create</Button>
          </form>
        </Card>
      )}

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No assets registered yet." />}
      {data && data.items.length > 0 && (
        <DataTable
          rows={data.items}
          columns={[
            { header: 'Name', render: (r) => r.name },
            { header: 'Type', render: (r) => r.entity_type },
            { header: 'Status', render: (r) => <StatusPill status={r.status} /> },
            {
              header: 'Coordinates',
              render: (r) => (r.latitude !== null && r.longitude !== null ? `${r.latitude.toFixed(3)}, ${r.longitude.toFixed(3)}` : <span className="text-slate-500">not provided</span>),
            },
          ]}
        />
      )}
    </div>
  )
}
