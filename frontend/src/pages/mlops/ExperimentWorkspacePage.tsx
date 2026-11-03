import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { mlopsApi } from '../../api/mlops'
import { useAuth } from '../../context/auth'
import type { Comparison, ExperimentRun, ModelVersion } from '../../types/mlops'
import type { Page } from '../../types/api'
import { DataTable } from '../../components/tables/DataTable'
import { Button, EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatusPill, inputClass } from '../../components/ui/Primitives'
import { MetricCell, Notice } from '../../components/mlops/shared'
import { canReview, fmtDate, shortHash } from '../../components/mlops/format'
import { Pager } from './MlopsRegistryPage'

/** Experiment workspace: run an evaluation, inspect reproducibility, compare compatible runs. */
export function ExperimentWorkspacePage() {
  const { user } = useAuth()
  const [runs, setRuns] = useState<Page<ExperimentRun> | null>(null)
  const [models, setModels] = useState<ModelVersion[]>([])
  const [status, setStatus] = useState('')
  const [modelId, setModelId] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<ExperimentRun | null>(null)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [compareError, setCompareError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [showNew, setShowNew] = useState(false)

  const load = useCallback(() => {
    setLoading(true); setError(null)
    mlopsApi.experiments({ status, model_record_id: modelId }, page).then(setRuns).catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [status, modelId, page])
  useEffect(load, [load])
  useEffect(() => { mlopsApi.versions({}, 1, 100).then((p) => setModels(p.items)).catch(() => setModels([])) }, [])

  const open = (r: ExperimentRun) => {
    setComparison(null); setCompareError(null)
    mlopsApi.experiment(r.id).then((d) => {
      setSelected(d)
      if (d.status === 'succeeded') mlopsApi.comparison(d.id).then(setComparison).catch((e) => setCompareError(e.message))
    }).catch((e) => setError(e.message))
  }

  return (
    <div>
      <PageHeader
        title="Experiment Workspace"
        description="Each run records what was evaluated, on which dataset fingerprint, with which settings and which metric implementation. Classification runs score the predictions you submit — AEGIS does not execute your classifier. Detection runs execute a registered adapter on a synthetic fixture."
        actions={canReview(user?.role) ? <Button onClick={() => setShowNew(true)}>New evaluation run</Button> : undefined}
      />
      {notice && <div className="mb-3 rounded-md border border-status-good/40 bg-status-good/10 px-3 py-2 text-sm text-status-good">{notice}</div>}
      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <Field label="Model version">
          <select className={inputClass} value={modelId} onChange={(e) => { setModelId(e.target.value); setPage(1) }}>
            <option value="">All</option>{models.filter((m) => m.task_type).map((m) => <option key={m.id} value={m.id}>{m.name} {m.version}</option>)}
          </select>
        </Field>
        <Field label="Status">
          <select className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
            <option value="">All</option><option value="succeeded">succeeded</option><option value="failed">failed</option><option value="running">running</option>
          </select>
        </Field>
      </div>
      {error && <ErrorState message={error} />}
      {loading && <Spinner />}
      {!loading && !error && runs && (runs.items.length === 0 ? <EmptyState message="No experiment runs match. Start a new evaluation run to create the first one." /> : (
        <>
          <DataTable rows={runs.items} onRowClick={open} columns={[
            { header: 'Run', render: (r) => <div><div className="text-slate-100">{r.experiment_name}</div><div className="text-xs text-slate-500">{fmtDate(r.started_at)} · v{r.model_version}</div></div> },
            { header: 'Status', render: (r) => <StatusPill status={r.status} /> },
            { header: 'Dataset', render: (r) => <span>{r.dataset_name}@{r.dataset_version}{r.is_synthetic && <span className="ml-1 text-status-warning">synthetic</span>}</span> },
            { header: 'Samples', render: (r) => r.sample_count ?? '—' },
            { header: 'Run fingerprint', render: (r) => <span className="font-mono text-xs">{shortHash(r.run_fingerprint)}</span> },
          ]} />
          <Pager page={runs.page} size={runs.page_size} total={runs.total} onPage={setPage} />
        </>
      ))}

      {selected && (
        <Modal title={`Run: ${selected.experiment_name}`} onClose={() => setSelected(null)}>
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-2"><StatusPill status={selected.status} /><span className="text-xs text-slate-500">{selected.duration_ms != null ? `${selected.duration_ms} ms` : ''}</span></div>
            {selected.performance_claim && <Notice tone={selected.is_synthetic ? 'warning' : 'info'}>{selected.performance_claim}</Notice>}
            {selected.status === 'failed' && <ErrorState message={`${selected.error_category ?? 'failed'}: ${selected.error_message ?? 'no detail'}`} />}
            {selected.metrics && (
              <table className="w-full text-left text-xs"><thead><tr className="text-slate-500"><th className="py-1">Metric</th><th>Value</th></tr></thead>
                <tbody>{Object.entries(selected.metrics).map(([k, m]) => <tr key={k} className="border-t border-charcoal-700/60"><td className="py-1 pr-3 text-slate-300">{k}</td><td><MetricCell metric={m} /></td></tr>)}</tbody></table>
            )}
            <dl className="space-y-1 text-xs text-slate-400">
              <div>Dataset fingerprint: <span className="font-mono">{shortHash(selected.dataset_fingerprint)}</span></div>
              <div>Config fingerprint: <span className="font-mono">{shortHash(selected.config_fingerprint)}</span></div>
              <div>Run fingerprint: <span className="font-mono">{shortHash(selected.run_fingerprint)}</span></div>
              {selected.reproducibility && <div>Metric implementation: {String((selected.reproducibility as Record<string, unknown>).metric_implementation_version ?? '—')} · Python {String((selected.reproducibility as Record<string, unknown>).python_version ?? '—')}</div>}
              {selected.limitations && <div>Limitations: {selected.limitations}</div>}
            </dl>
            {comparison?.status === 'compared' && (
              <div><h4 className="mb-1 text-xs font-semibold text-slate-200">Vs selected baseline</h4><p className="text-xs text-slate-400">{comparison.summary.statement}</p>
                <ul className="mt-1 space-y-0.5 text-xs">{comparison.metrics.map((m) => <li key={m.metric} className="text-slate-300">{m.metric}: {m.change.replace('_', ' ')}{m.absolute_difference != null ? ` (${m.absolute_difference > 0 ? '+' : ''}${m.absolute_difference})` : ''}{m.exceeds_review_threshold ? ' · exceeds review threshold' : ''}</li>)}</ul></div>
            )}
            {comparison && comparison.status !== 'compared' && <p className="text-xs text-slate-500">{comparison.message}</p>}
            {compareError && <p className="text-xs text-status-warning">Comparison unavailable: {compareError}</p>}
            <div className="flex justify-between gap-2">
              <Link className="text-xs text-accent-400" to={`/mlops/models/${selected.model_record_id}`}>Open model version</Link>
              {selected.status === 'succeeded' && canReview(user?.role) && (
                <Button variant="secondary" onClick={() => mlopsApi.selectBaseline(selected.id, 'Selected from the experiment workspace').then(() => { setNotice('Baseline selected for this task and dataset.'); setSelected(null) }).catch((e) => setError(e.message))}>Use as baseline</Button>
              )}
            </div>
          </div>
        </Modal>
      )}
      {showNew && <NewRunModal models={models} onClose={() => setShowNew(false)} onDone={(r) => { setShowNew(false); setNotice(r.status === 'succeeded' ? 'Run completed.' : `Run recorded as ${r.status}.`); load(); open(r) }} />}
    </div>
  )
}

function parseSamples(text: string): { ok: true; samples: { true_label: string; predicted_label: string }[] } | { ok: false; error: string } {
  const rows = text.split('\n').map((l) => l.trim()).filter(Boolean)
  if (rows.length === 0) return { ok: false, error: 'Enter at least one "true_label,predicted_label" row.' }
  if (rows.length > 5000) return { ok: false, error: 'At most 5000 rows can be submitted from this form.' }
  const samples = []
  for (const [i, line] of rows.entries()) {
    const parts = line.split(',').map((s) => s.trim())
    if (parts.length !== 2 || !parts[0] || !parts[1]) return { ok: false, error: `Row ${i + 1} must be "true_label,predicted_label".` }
    samples.push({ true_label: parts[0], predicted_label: parts[1] })
  }
  return { ok: true, samples }
}

function NewRunModal({ models, onClose, onDone }: { models: ModelVersion[]; onClose: () => void; onDone: (r: ExperimentRun) => void }) {
  const eligible = models.filter((m) => m.task_type && m.owned_by_your_organization && m.lifecycle_state !== 'archived')
  const [modelId, setModelId] = useState(eligible[0]?.id ?? '')
  const model = eligible.find((m) => m.id === modelId)
  const [name, setName] = useState('')
  const [dsName, setDsName] = useState('')
  const [dsVersion, setDsVersion] = useState('1')
  const [synthetic, setSynthetic] = useState(false)
  const [positive, setPositive] = useState('')
  const [text, setText] = useState('')
  const [count, setCount] = useState(20)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!model) return
    setError(null)
    const base = { model_record_id: model.id, experiment_name: name, idempotency_key: `ui-${crypto.randomUUID()}` }
    let body
    if (model.task_type === 'object_detection') body = { ...base, detection: { sample_count: count } }
    else {
      const parsed = parseSamples(text)
      if (!parsed.ok) { setError(parsed.error); return }
      body = { ...base, classification: { dataset_name: dsName, dataset_version: dsVersion, is_synthetic: synthetic, positive_label: positive.trim() || undefined, labels: positive.trim() ? Array.from(new Set(parsed.samples.flatMap((s) => [s.true_label, s.predicted_label]))) : undefined, samples: parsed.samples } }
    }
    setBusy(true)
    try { onDone(await mlopsApi.createExperiment(body)) } catch (e) { setError((e as Error).message); setBusy(false) }
  }

  return (
    <Modal title="New evaluation run" onClose={onClose}>
      {eligible.length === 0 ? <EmptyState message="Register a model version owned by your organization first." /> : (
        <div className="space-y-3">
          <Field label="Model version"><select className={inputClass} value={modelId} onChange={(e) => setModelId(e.target.value)}>{eligible.map((m) => <option key={m.id} value={m.id}>{m.name} {m.version} ({m.task_type})</option>)}</select></Field>
          <Field label="Experiment name"><input className={inputClass} value={name} maxLength={200} onChange={(e) => setName(e.target.value)} /></Field>
          {model?.task_type === 'object_detection' ? (
            <>
              <Notice>Runs the registered detector adapter on a built-in synthetic fixture. Results describe the fixture only — not real-world performance.</Notice>
              <Field label="Synthetic samples (1–200)"><input type="number" min={1} max={200} className={inputClass} value={count} onChange={(e) => setCount(Number(e.target.value))} /></Field>
            </>
          ) : (
            <>
              <Notice>Submit predictions your classifier already produced. AEGIS scores them against the labels you provide; it does not run your model. Metrics with no ground truth are reported undefined, never zero.</Notice>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Dataset name"><input className={inputClass} value={dsName} maxLength={200} onChange={(e) => setDsName(e.target.value)} /></Field>
                <Field label="Dataset version"><input className={inputClass} value={dsVersion} maxLength={50} onChange={(e) => setDsVersion(e.target.value)} /></Field>
              </div>
              <label className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={synthetic} onChange={(e) => setSynthetic(e.target.checked)} /> This dataset is synthetic</label>
              <Field label="Positive label (optional; enables precision/recall/F1)"><input className={inputClass} value={positive} maxLength={100} onChange={(e) => setPositive(e.target.value)} /></Field>
              <Field label="Rows: true_label,predicted_label (one per line)"><textarea className={`${inputClass} font-mono`} rows={6} value={text} onChange={(e) => setText(e.target.value)} placeholder={'threat,threat\nbenign,threat'} /></Field>
            </>
          )}
          {error && <ErrorState message={error} />}
          <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy || !name || (model?.task_type === 'classification' && (!dsName || !dsVersion))}>Run</Button></div>
        </div>
      )}
    </Modal>
  )
}
