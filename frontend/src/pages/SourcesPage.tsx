import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { DataSource, Page } from '../types/api'
import { useAuth } from '../context/auth'
import { DataTable } from '../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

const CONNECTOR_DRIVEN_TYPES = new Set(['http_api', 'synthetic_demo', 'synthetic_generator'])

export function SourcesPage() {
  const { user } = useAuth()
  const [data, setData] = useState<Page<DataSource> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [sourceType, setSourceType] = useState('manual')
  const [connectionMode, setConnectionMode] = useState('file_upload')
  const [ownerTeam, setOwnerTeam] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [rowBusy, setRowBusy] = useState<string | null>(null)
  const [rowMessage, setRowMessage] = useState<{ id: string; text: string; tone: 'good' | 'bad' } | null>(null)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst'

  function load() {
    api.sources
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
      await api.sources.create({ name, source_type: sourceType, connection_mode: connectionMode, owner_team: ownerTeam || undefined })
      setName('')
      setOwnerTeam('')
      setShowForm(false)
      load()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not create source.')
    }
  }

  async function withRowBusy(source: DataSource, fn: () => Promise<string>) {
    setRowBusy(source.id)
    setRowMessage(null)
    try {
      const text = await fn()
      setRowMessage({ id: source.id, text, tone: 'good' })
      load()
    } catch (err) {
      setRowMessage({ id: source.id, text: err instanceof ApiError ? err.message : 'Action failed.', tone: 'bad' })
    } finally {
      setRowBusy(null)
    }
  }

  async function handleReliabilityChange(source: DataSource) {
    const weightStr = window.prompt(`New reliability weight for "${source.name}" (0.0 - 1.0):`, String(source.reliability_weight))
    if (weightStr === null) return
    const weight = Number(weightStr)
    if (Number.isNaN(weight) || weight < 0 || weight > 1) {
      setRowMessage({ id: source.id, text: 'Weight must be a number between 0 and 1.', tone: 'bad' })
      return
    }
    const reason = window.prompt('Documented reason for this change (required -- Section 16):')
    if (!reason) return
    await withRowBusy(source, async () => {
      await api.sources.setReliability(source.id, weight, reason)
      return `Reliability weight set to ${weight.toFixed(2)}.`
    })
  }

  return (
    <div>
      <PageHeader
        title="Data Source Registry"
        description="Registered origins of events -- no credentials are stored here (see Security Baseline). Connector-driven sources (http_api, synthetic_demo) can be run directly; file-upload sources only ever receive an uploaded file."
        actions={canManage && <Button onClick={() => setShowForm((s) => !s)}>{showForm ? 'Cancel' : 'Register source'}</Button>}
      />

      {showForm && (
        <Card className="mb-5 max-w-md">
          <form onSubmit={handleCreate} className="space-y-3">
            <Field label="Name">
              <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field label="Source type">
              <input className={inputClass} value={sourceType} onChange={(e) => setSourceType(e.target.value)} required />
            </Field>
            <Field label="Connection mode">
              <select className={inputClass} value={connectionMode} onChange={(e) => setConnectionMode(e.target.value)}>
                <option value="file_upload">file_upload (receives uploads only)</option>
                <option value="polling">polling (can be run on demand)</option>
                <option value="push">push (future inbound webhook)</option>
                <option value="internal">internal (another part of this app)</option>
              </select>
            </Field>
            <Field label="Owner / team (optional)">
              <input className={inputClass} value={ownerTeam} onChange={(e) => setOwnerTeam(e.target.value)} />
            </Field>
            {formError && <ErrorState message={formError} />}
            <Button type="submit">Create</Button>
          </form>
        </Card>
      )}

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No data sources registered yet." />}
      {data && data.items.length > 0 && (
        <DataTable
          rows={data.items}
          columns={[
            { header: 'Name', render: (r) => r.name },
            { header: 'Type', render: (r) => r.source_type },
            { header: 'Owner', render: (r) => r.owner_team ?? <span className="text-slate-500">--</span> },
            { header: 'Enabled', render: (r) => <StatusPill status={r.enabled ? 'active' : 'inactive'} /> },
            { header: 'Status', render: (r) => <StatusPill status={r.status} /> },
            { header: 'Reliability', render: (r) => r.reliability_weight.toFixed(2) },
            { header: 'Last error', render: (r) => r.last_error_category ?? <span className="text-slate-500">none</span> },
            { header: 'Last ingestion', render: (r) => (r.last_ingestion_attempt_at ? new Date(r.last_ingestion_attempt_at).toLocaleString() : 'never') },
            {
              header: 'Actions',
              render: (r) =>
                canManage ? (
                  <div className="flex flex-wrap items-center gap-1.5">
                    {CONNECTOR_DRIVEN_TYPES.has(r.source_type) && (
                      <Button
                        variant="secondary"
                        disabled={rowBusy === r.id || !r.enabled}
                        onClick={() => withRowBusy(r, async () => {
                          const job = await api.sources.run(r.id)
                          return `Run ${job.status} -- accepted ${job.accepted_count}, rejected ${job.rejected_count}, duplicate ${job.duplicate_count}.`
                        })}
                      >
                        Run
                      </Button>
                    )}
                    <Button
                      variant="secondary"
                      disabled={rowBusy === r.id}
                      onClick={() => withRowBusy(r, async () => {
                        const result = await api.sources.validateConfig(r.id)
                        return result.valid ? 'Configuration is valid.' : `Invalid: ${result.errors.join('; ')}`
                      })}
                    >
                      Validate config
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={rowBusy === r.id}
                      onClick={() => withRowBusy(r, async () => {
                        const result = await api.sources.checkConnectivity(r.id)
                        if (!result.applicable) return 'Not applicable -- this source only receives uploads.'
                        return result.ok ? 'Connectivity OK.' : `Connectivity failed: ${result.detail ?? 'unknown error'}`
                      })}
                    >
                      Check connectivity
                    </Button>
                    <Button
                      variant={r.enabled ? 'danger' : 'primary'}
                      disabled={rowBusy === r.id}
                      onClick={() => withRowBusy(r, async () => {
                        const updated = r.enabled ? await api.sources.disable(r.id) : await api.sources.enable(r.id)
                        return updated.enabled ? 'Source enabled.' : 'Source disabled -- new ingestion jobs are blocked.'
                      })}
                    >
                      {r.enabled ? 'Disable' : 'Enable'}
                    </Button>
                    <Button variant="secondary" disabled={rowBusy === r.id} onClick={() => handleReliabilityChange(r)}>
                      Set reliability
                    </Button>
                    {rowMessage && rowMessage.id === r.id && (
                      <div className={`mt-1 w-full text-xs ${rowMessage.tone === 'good' ? 'text-status-good' : 'text-status-critical'}`}>
                        {rowMessage.text}
                      </div>
                    )}
                  </div>
                ) : (
                  <span className="text-slate-500">read-only</span>
                ),
            },
          ]}
        />
      )}
    </div>
  )
}
