import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { mlopsApi } from '../../api/mlops'
import { useAuth } from '../../context/auth'
import type { Comparison, ExperimentRun, LifecycleEvent, MetricHistory, ModelVersion, TransitionAction } from '../../types/mlops'
import { Button, Card, EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatusPill, Tabs, inputClass } from '../../components/ui/Primitives'
import { DataTable } from '../../components/tables/DataTable'
import { MetricTrend } from '../../components/mlops/MetricTrend'
import { MetricCell, Notice } from '../../components/mlops/shared'
import { canApprove, canReview, fmtDate, shortHash } from '../../components/mlops/format'

const ACTION_LABEL: Record<TransitionAction, string> = {
  request_review: 'Request review', reject_review: 'Return to registered', approve: 'Approve', revoke_approval: 'Revoke approval',
  deprecate: 'Deprecate', reactivate: 'Reactivate', archive: 'Archive',
}
// Which actions make sense per state (the server validates the real state machine and the caller's permission).
const ACTIONS: Record<string, TransitionAction[]> = {
  registered: ['request_review', 'approve', 'deprecate'], review_required: ['approve', 'reject_review'], approved: ['revoke_approval', 'deprecate'],
  deprecated: ['reactivate', 'archive'], archived: [],
}
const APPROVER_ACTIONS: TransitionAction[] = ['approve', 'reject_review', 'revoke_approval', 'deprecate', 'reactivate', 'archive']

export function ModelVersionDetailPage() {
  const { modelId = '' } = useParams()
  const { user } = useAuth()
  const [model, setModel] = useState<ModelVersion | null>(null)
  const [events, setEvents] = useState<LifecycleEvent[]>([])
  const [runs, setRuns] = useState<ExperimentRun[]>([])
  const [history, setHistory] = useState<MetricHistory | null>(null)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [tab, setTab] = useState('overview')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [pending, setPending] = useState<TransitionAction | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    setError(null)
    mlopsApi.version(modelId).then((m) => {
      setModel(m)
      if (m.task_type) {
        const metric = m.task_type === 'classification' ? 'accuracy' : 'recall'
        mlopsApi.metricHistory({ metric, task: m.task_type, model_record_id: m.id }).then(setHistory).catch(() => setHistory(null))
      }
    }).catch((e) => setError(e.message))
    mlopsApi.history(modelId).then((r) => setEvents(r.items)).catch(() => setEvents([]))
    mlopsApi.experiments({ model_record_id: modelId }, 1, 10).then((p) => {
      setRuns(p.items)
      const latest = p.items.find((r) => r.status === 'succeeded')
      if (latest) mlopsApi.comparison(latest.id).then(setComparison).catch(() => setComparison(null))
      else setComparison(null)
    }).catch(() => setRuns([]))
  }, [modelId])
  useEffect(load, [load])

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setError(null); setNotice(null)
    try { await fn(); setNotice(ok); setPending(null); setReason(''); load() } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  if (error && !model) return <ErrorState message={error} />
  if (!model) return <Spinner />
  const allowed = (ACTIONS[model.lifecycle_state] ?? []).filter((a) => (APPROVER_ACTIONS.includes(a) ? canApprove(user?.role) : canReview(user?.role)))
  const owned = model.owned_by_your_organization

  return (
    <div>
      <PageHeader title={`${model.name} ${model.version}`} description={<span>Task: {model.task_type ?? 'unspecified'} · <Link className="text-accent-400" to="/mlops/models">Back to registry</Link></span>}
        actions={<div className="flex flex-wrap items-center gap-2"><StatusPill status={model.lifecycle_state} />{allowed.map((a) => <Button key={a} variant={a === 'approve' ? 'primary' : 'secondary'} onClick={() => { setPending(a); setReason('') }}>{ACTION_LABEL[a]}</Button>)}</div>} />
      {error && <ErrorState message={error} />}
      {notice && <div className="mb-3 rounded-md border border-status-good/40 bg-status-good/10 px-3 py-2 text-sm text-status-good">{notice}</div>}
      {model.serving_note && <Notice>{model.serving_note}</Notice>}
      {model.scope === 'platform' && <Notice>This is a platform-level (shared) registry row created before organization ownership existed. Its identity fields are not enforced immutable.</Notice>}
      <Tabs tabs={[{ key: 'overview', label: 'Overview' }, { key: 'evaluation', label: 'Evaluation' }, { key: 'history', label: 'Lifecycle history' }]} active={tab} onChange={setTab} />

      {tab === 'overview' && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card><dl className="space-y-2 text-sm">
            {([['Legacy status (CV inference gate)', model.legacy_status], ['Model type', model.model_type], ['Adapter', model.adapter_key ?? '—'], ['Supported media', model.supported_media_types.join(', ') || '—'],
              ['Input schema', model.input_schema_version ?? '—'], ['Output schema', model.output_schema_version ?? '—'], ['Registered', fmtDate(model.created_at)], ['Documentation', model.documentation_ref ?? '—']] as [string, string][]).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4"><dt className="text-slate-500">{k}</dt><dd className="text-right text-slate-200">{v}</dd></div>
            ))}
          </dl></Card>
          <Card>
            <h3 className="mb-2 text-sm font-semibold text-slate-100">Artifact</h3>
            <p className="text-sm text-slate-300">{model.artifact_reference ?? 'No artifact reference'}</p>
            <p className={`mt-1 text-sm ${model.artifact.available ? 'text-status-good' : 'text-status-warning'}`}>{model.artifact.available ? 'Available' : `Unavailable${model.artifact.reason ? ` — ${model.artifact.reason}` : ''}`}</p>
            <p className="mt-1 text-xs text-slate-500">Digest: <span className="font-mono">{shortHash(model.artifact_digest)}</span>{model.artifact_digest ? '…' : ''}</p>
            {owned && canReview(user?.role) && (
              <div className="mt-3"><Button variant="secondary" disabled={busy} onClick={() => run(async () => {
                const r = await mlopsApi.verifyArtifact(model.id)
                if (!r.available) throw new Error(`Artifact verification failed: ${r.reason ?? 'unavailable'}${r.review_signal_id ? ' (a review signal was raised)' : ''}`)
              }, 'Artifact verified: available and the digest matches.')}>Verify artifact now</Button></div>
            )}
          </Card>
          <Card className="md:col-span-2"><h3 className="mb-2 text-sm font-semibold text-slate-100">Release notes</h3>
            {/* Plain text only: never rendered as HTML. */}
            <p className="whitespace-pre-wrap text-sm text-slate-300">{model.release_notes || 'None recorded.'}</p>
            {model.framework_metadata && Object.keys(model.framework_metadata).length > 0 && <pre className="mt-3 overflow-x-auto rounded-sm bg-charcoal-900 p-3 text-xs text-slate-400">{JSON.stringify(model.framework_metadata, null, 2)}</pre>}
          </Card>
        </div>
      )}

      {tab === 'evaluation' && (
        <div className="space-y-4">
          <Card>
            <div className="flex items-center justify-between"><h3 className="text-sm font-semibold text-slate-100">Derived evaluation status</h3><StatusPill status={model.evaluation.status} /></div>
            <p className="mt-1 text-xs text-slate-500">Computed from the latest runs and open review signals at read time. “passed” means no open regression or floor signal and a fresh successful run — it is not a quality claim.</p>
          </Card>
          {history && (
            <Card><MetricTrend metric={history.metric} windowDays={history.window_days} points={history.points} />
              {history.note && <p className="mt-2 text-xs text-status-warning">{history.note}</p>}
              {history.runs_without_this_metric_defined > 0 && <p className="mt-1 text-xs text-slate-500">{history.runs_without_this_metric_defined} run(s) had this metric undefined and are not plotted.</p>}
            </Card>
          )}
          {comparison && comparison.status === 'compared' && (
            <Card>
              <h3 className="mb-1 text-sm font-semibold text-slate-100">Latest run vs selected baseline</h3>
              <p className="mb-2 text-xs text-slate-400">{comparison.summary.statement}</p>
              {comparison.small_sample_warning && <Notice tone="warning">Small sample: differences may be noise.</Notice>}
              <DataTable rows={comparison.metrics.map((m) => ({ ...m, id: m.metric }))} columns={[
                { header: 'Metric', render: (m) => m.metric },
                { header: 'Baseline', render: (m) => m.baseline.value ?? 'undefined' },
                { header: 'Candidate', render: (m) => m.candidate.value ?? 'undefined' },
                { header: 'Δ abs', render: (m) => m.absolute_difference ?? '—' },
                { header: 'Change', render: (m) => <span>{m.change.replace('_', ' ')}{m.exceeds_review_threshold && <span className="ml-1 text-status-warning">· exceeds review threshold ({m.review_threshold})</span>}{m.distinguishable_at_95 === false && <span className="ml-1 text-xs text-slate-500">· within overlapping 95% intervals</span>}</span> },
              ]} />
              <ul className="mt-2 list-disc pl-5 text-xs text-slate-500">{comparison.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
            </Card>
          )}
          {comparison && comparison.status !== 'compared' && <Notice>{comparison.message}</Notice>}
          <h3 className="text-sm font-semibold text-slate-100">Recent runs</h3>
          {runs.length === 0 ? <EmptyState message="No experiment runs for this version yet." /> : (
            <DataTable rows={runs} columns={[
              { header: 'Run', render: (r) => <div><div className="text-slate-100">{r.experiment_name}</div><div className="text-xs text-slate-500">{fmtDate(r.started_at)}</div></div> },
              { header: 'Status', render: (r) => <StatusPill status={r.status} /> },
              { header: 'Dataset', render: (r) => `${r.dataset_name}@${r.dataset_version}${r.is_synthetic ? ' (synthetic)' : ''}` },
              { header: 'Primary metric', render: (r) => r.metrics ? <MetricCell metric={r.metrics[r.task === 'classification' ? 'accuracy' : 'recall']} /> : <span className="text-slate-500">{r.error_message ?? 'no metrics'}</span> },
              { header: 'Fingerprint', render: (r) => <span className="font-mono text-xs">{shortHash(r.run_fingerprint)}</span> },
            ]} />
          )}
        </div>
      )}

      {tab === 'history' && (
        events.length === 0 ? <EmptyState message="No lifecycle events recorded." /> : (
          <DataTable rows={events} columns={[
            { header: 'When', render: (e) => fmtDate(e.created_at) },
            { header: 'Action', render: (e) => e.action.replace('_', ' ') },
            { header: 'Transition', render: (e) => `${e.from_state ?? '∅'} → ${e.to_state}` },
            { header: 'By', render: (e) => (e.actor_scope === 'your_organization' ? 'your organization' : e.actor_scope.replace('_', ' ')) },
            { header: 'Reason', render: (e) => e.reason ?? '—' },
          ]} />
        )
      )}

      {pending && (
        <Modal title={ACTION_LABEL[pending]} onClose={() => setPending(null)}>
          <p className="mb-3 text-xs text-slate-400">A reason is required and is stored in the audit trail. Approval additionally needs a recent successful evaluation, no unresolved serious/critical signals and a different approver than the registrant — the server checks all of this.</p>
          <Field label="Reason (3–1000 characters)"><textarea className={inputClass} rows={3} value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} /></Field>
          <div className="mt-3 flex justify-end gap-2"><Button variant="secondary" onClick={() => setPending(null)}>Cancel</Button>
            <Button disabled={busy || reason.trim().length < 3} onClick={() => run(() => mlopsApi.transition(model.id, pending, reason.trim()), `${ACTION_LABEL[pending]}: done.`)}>Confirm</Button></div>
        </Modal>
      )}
    </div>
  )
}
