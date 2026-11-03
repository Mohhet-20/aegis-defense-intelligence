import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type { SyncConflict, SyncConflictResolutionStrategy } from '../../types/api'
import { Button, Card, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../../components/ui/Primitives'

function formatDateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '--'
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between border-b border-charcoal-700/50 py-2 text-sm last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  )
}

const STRATEGIES: { key: SyncConflictResolutionStrategy; label: string; description: string }[] = [
  { key: 'keep_central', label: 'Keep central', description: "Discard the device's submitted version; the central version stands." },
  { key: 'keep_local', label: 'Keep local', description: "Accept the device's submitted version in place of the central one." },
  { key: 'merged', label: 'Merged', description: 'A manual merge was produced outside this tool -- requires a note describing it.' },
]

export function EdgeConflictDetailPage() {
  const { conflictId } = useParams<{ conflictId: string }>()
  const { user } = useAuth()
  const [conflict, setConflict] = useState<SyncConflict | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [strategy, setStrategy] = useState<SyncConflictResolutionStrategy>('keep_central')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [resolveError, setResolveError] = useState<string | null>(null)

  const canResolve = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  useEffect(() => {
    if (!conflictId) return
    api.edgeConflicts
      .get(conflictId)
      .then(setConflict)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load conflict.'))
  }, [conflictId])

  async function handleResolve() {
    if (!conflict) return
    if (strategy === 'merged' && !note.trim()) {
      setResolveError('A note describing the merge is required when choosing "merged".')
      return
    }
    setSubmitting(true)
    setResolveError(null)
    try {
      const updated = await api.edgeConflicts.resolve(conflict.id, strategy, note || undefined)
      setConflict(updated)
      setNote('')
    } catch (err) {
      setResolveError(err instanceof ApiError ? err.message : 'Resolution failed.')
    } finally {
      setSubmitting(false)
    }
  }

  if (error) return <ErrorState message={error} />
  if (!conflict) return <Spinner />

  const isResolved = conflict.resolution_status === 'resolved'

  return (
    <div>
      <PageHeader
        title={`Conflict -- ${conflict.record_type}`}
        description={
          <>
            <Link to="/edge/conflicts" className="text-accent-400 hover:underline">
              Conflict Review
            </Link>{' '}
            / <span className="font-mono">{conflict.client_record_id}</span>
          </>
        }
      />

      <Card className="mb-4">
        <Row label="Device" value={<span className="font-mono text-xs">{conflict.device_id}</span>} />
        <Row label="Sync record" value={<span className="font-mono text-xs">{conflict.sync_record_id}</span>} />
        <Row label="Conflict reason" value={conflict.conflict_reason} />
        <Row label="Status" value={<StatusPill status={conflict.resolution_status} />} />
        <Row label="Created" value={formatDateTime(conflict.created_at)} />
        {isResolved && (
          <>
            <Row label="Resolution strategy" value={conflict.resolution_strategy?.replace(/_/g, ' ') ?? '--'} />
            <Row label="Resolved at" value={formatDateTime(conflict.resolved_at)} />
            <Row label="Resolution note" value={conflict.resolution_note ?? '--'} />
          </>
        )}
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Local version (from device)</h2>
          <pre className="max-h-96 overflow-auto rounded-md bg-charcoal-900 p-3 text-xs text-slate-300">
            {JSON.stringify(conflict.local_version, null, 2)}
          </pre>
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Central version</h2>
          <pre className="max-h-96 overflow-auto rounded-md bg-charcoal-900 p-3 text-xs text-slate-300">
            {JSON.stringify(conflict.central_version, null, 2)}
          </pre>
        </Card>
      </div>

      <Card className="mt-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Resolve</h2>
        {isResolved ? (
          <p className="text-sm text-slate-400">This conflict has already been resolved and cannot be resolved again.</p>
        ) : canResolve ? (
          <div className="grid gap-3">
            <div className="grid gap-2 sm:grid-cols-3">
              {STRATEGIES.map((s) => (
                <label
                  key={s.key}
                  className={`cursor-pointer rounded-md border p-3 text-sm ${
                    strategy === s.key ? 'border-accent-500 bg-accent-500/10' : 'border-charcoal-600 bg-charcoal-900'
                  }`}
                >
                  <div className="mb-1 flex items-center gap-2">
                    <input type="radio" name="strategy" checked={strategy === s.key} onChange={() => setStrategy(s.key)} />
                    <span className="font-medium text-slate-200">{s.label}</span>
                  </div>
                  <p className="text-xs text-slate-500">{s.description}</p>
                </label>
              ))}
            </div>
            <Field label={strategy === 'merged' ? 'Merge note (required)' : 'Note (optional)'}>
              <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
            </Field>
            {resolveError && <ErrorState message={resolveError} />}
            <div>
              <Button onClick={handleResolve} disabled={submitting}>
                {submitting ? 'Resolving…' : 'Resolve conflict'}
              </Button>
            </div>
          </div>
        ) : (
          <p className="text-xs text-slate-500">Administrator, analyst, or investigator role required to resolve conflicts.</p>
        )}
      </Card>
    </div>
  )
}
