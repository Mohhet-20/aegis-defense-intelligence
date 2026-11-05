import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api/client'
import type { CVModel, Page } from '../../types/api'
import { useAuth } from '../../context/auth'
import { DataTable } from '../../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../../components/ui/Primitives'

export function ModelRegistryPage() {
  const { user } = useAuth()
  const [data, setData] = useState<Page<CVModel> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [version, setVersion] = useState('')
  const [adapterKey, setAdapterKey] = useState('mock_detector_v1')
  const [mediaTypes, setMediaTypes] = useState<string[]>(['image', 'video'])
  const [registerError, setRegisterError] = useState<string | null>(null)
  const [registering, setRegistering] = useState(false)

  const canManage = user?.role === 'administrator'

  function load() {
    api.cvModels
      .list(1, 50)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [])

  function toggleMediaType(type: string) {
    setMediaTypes((prev) => (prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]))
  }

  async function handleRegister(e: FormEvent) {
    e.preventDefault()
    if (!name || !version || mediaTypes.length === 0) return
    setRegistering(true)
    setRegisterError(null)
    try {
      await api.cvModels.register({ name, version, adapter_key: adapterKey, supported_media_types: mediaTypes })
      setName('')
      setVersion('')
      load()
    } catch (err) {
      setRegisterError(err instanceof ApiError ? err.message : 'Registration failed.')
    } finally {
      setRegistering(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Model Registry"
        description="Extends the core ModelRecord table -- never a parallel CVModel entity. adapter_key names a key in a fixed, closed allow-list (app/cv/adapters/registry.py); it can never cause arbitrary code to run. See docs/ml/MODEL_REGISTRY.md."
      />

      {canManage && (
        <Card className="mb-5 max-w-lg">
          <form onSubmit={handleRegister} className="space-y-3">
            <Field label="Name">
              <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Version">
              <input className={inputClass} value={version} onChange={(e) => setVersion(e.target.value)} />
            </Field>
            <Field label="Adapter">
              <select className={inputClass} value={adapterKey} onChange={(e) => setAdapterKey(e.target.value)}>
                <option value="mock_detector_v1">mock_detector_v1 (deterministic, no real inference)</option>
                <option value="opencv_hog_person_v1">opencv_hog_person_v1 (real -- OpenCV HOG+SVM person detector)</option>
              </select>
            </Field>
            <Field label="Supported media types">
              <div className="flex gap-4 text-sm text-slate-300">
                {['image', 'video'].map((type) => (
                  <label key={type} className="flex items-center gap-1.5">
                    <input type="checkbox" checked={mediaTypes.includes(type)} onChange={() => toggleMediaType(type)} />
                    {type}
                  </label>
                ))}
              </div>
            </Field>
            {registerError && <ErrorState message={registerError} />}
            <Button type="submit" disabled={registering || !name || !version}>
              {registering ? 'Registering…' : 'Register model'}
            </Button>
          </form>
        </Card>
      )}

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No CV models registered yet." />}
      {data && data.items.length > 0 && (
        <DataTable
          rows={data.items}
          columns={[
            { header: 'Name', render: (m) => m.name },
            { header: 'Version', render: (m) => m.version },
            { header: 'Adapter', render: (m) => <span className="font-mono text-xs">{m.adapter_key}</span> },
            { header: 'Media types', render: (m) => m.supported_media_types.join(', ') },
            { header: 'Status', render: (m) => <StatusPill status={m.status} /> },
            { header: 'Registered', render: (m) => new Date(m.created_at).toLocaleString() },
          ]}
        />
      )}
    </div>
  )
}
