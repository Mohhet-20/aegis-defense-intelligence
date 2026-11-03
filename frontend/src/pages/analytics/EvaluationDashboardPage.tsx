import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type { CVModel, EvaluationOverviewRow, EvaluationSampleInput, Page } from '../../types/api'
import { ApiErrorView, SyntheticBadge } from '../../components/analytics/AnalyticsBits'
import { formatMetric } from '../../components/analytics/format'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import { Button, Card, EmptyState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../../components/ui/Primitives'
import { formatVersion } from '../../utils/version'

const SAMPLE_PLACEHOLDER = `[
  {"sample_ref": "s1", "true_label": "pos", "predicted_label": "pos", "positive_probability": 0.9},
  {"sample_ref": "s2", "true_label": "neg", "predicted_label": "neg", "positive_probability": 0.2}
]`

function headline(row: EvaluationOverviewRow): string {
  const m = row.headline_metrics
  if (row.status === 'failed') return 'no metrics (run failed)'
  return Object.entries(m)
    .map(([k, v]) => `${k.replace(/_/g, ' ')} ${typeof v === 'number' ? formatMetric(v, 2) : 'undefined'}`)
    .join(' · ')
}

export function EvaluationDashboardPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<EvaluationOverviewRow> | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [models, setModels] = useState<CVModel[]>([])
  const [showForm, setShowForm] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [modelId, setModelId] = useState('')
  const [datasetName, setDatasetName] = useState('')
  const [datasetVersion, setDatasetVersion] = useState('')
  const [datasetRef, setDatasetRef] = useState('')
  const [isSynthetic, setIsSynthetic] = useState<'' | 'true' | 'false'>('')
  const [positiveLabel, setPositiveLabel] = useState('')
  const [samplesText, setSamplesText] = useState('')

  const canEvaluate = user?.role === 'administrator' || user?.role === 'analyst'

  function load() {
    api.analytics.evaluations
      .overview({ page, page_size: 20 })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch(setError)
  }
  useEffect(load, [page])
  useEffect(() => {
    if (canEvaluate) api.cvModels.list(1, 100).then((p) => setModels(p.items)).catch(() => setModels([]))
  }, [canEvaluate])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    let samples: EvaluationSampleInput[]
    try {
      const parsed = JSON.parse(samplesText)
      if (!Array.isArray(parsed)) throw new Error('Samples must be a JSON array.')
      samples = parsed
    } catch (err) {
      setFormError(err instanceof Error ? `Samples are not valid JSON: ${err.message}` : 'Samples are not valid JSON.')
      return
    }
    if (isSynthetic === '') {
      setFormError('Declare whether the dataset is synthetic.')
      return
    }
    setSubmitting(true)
    try {
      const run = await api.analytics.evaluations.run({
        model_record_id: modelId.trim(),
        dataset_name: datasetName.trim(),
        dataset_version: datasetVersion.trim(),
        dataset_reference: datasetRef.trim() || null,
        is_synthetic: isSynthetic === 'true',
        positive_label: positiveLabel.trim() || null,
        samples,
      })
      navigate(`/analytics/evaluations/${run.id}`)
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Evaluation failed.')
      load()
    } finally {
      setSubmitting(false)
    }
  }

  function open(row: EvaluationOverviewRow) {
    if (row.kind === 'classification') navigate(`/analytics/evaluations/${row.id}`)
    else if (row.kind === 'detection') navigate('/cv/evaluation')
    else navigate('/tracking/evaluation')
  }

  return (
    <div>
      <PageHeader
        title="Model Evaluation Dashboard"
        description="Evaluations of registered models against labelled datasets. Every result is tied to an exact model version and dataset version; synthetic datasets are labelled and never presented as real-world performance."
        actions={canEvaluate ? <Button onClick={() => setShowForm((s) => !s)}>{showForm ? 'Close' : 'Run evaluation'}</Button> : undefined}
      />

      {showForm && canEvaluate && (
        <Card className="mb-6">
          <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
            <Field label="Model record ID">
              <input className={inputClass} list="eval-models" value={modelId} onChange={(e) => setModelId(e.target.value)} required />
              <datalist id="eval-models">
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{`${m.name} ${formatVersion(m.version)}`}</option>
                ))}
              </datalist>
            </Field>
            <Field label="Dataset is synthetic? (required)">
              <select className={inputClass} value={isSynthetic} onChange={(e) => setIsSynthetic(e.target.value as '' | 'true' | 'false')} required>
                <option value="">-- declare --</option>
                <option value="true">Yes, synthetic</option>
                <option value="false">No, real labelled data</option>
              </select>
            </Field>
            <Field label="Dataset name"><input className={inputClass} value={datasetName} onChange={(e) => setDatasetName(e.target.value)} required /></Field>
            <Field label="Dataset version"><input className={inputClass} value={datasetVersion} onChange={(e) => setDatasetVersion(e.target.value)} required /></Field>
            <Field label="Dataset reference (optional)"><input className={inputClass} value={datasetRef} onChange={(e) => setDatasetRef(e.target.value)} /></Field>
            <Field label="Positive label (needed if probabilities are supplied)"><input className={inputClass} value={positiveLabel} onChange={(e) => setPositiveLabel(e.target.value)} /></Field>
            <div className="md:col-span-2">
              <Field label="Samples (JSON array; true_label may be null for unlabelled rows, which are excluded and counted)">
                <textarea className={`${inputClass} h-40 font-mono text-xs`} value={samplesText} onChange={(e) => setSamplesText(e.target.value)} placeholder={SAMPLE_PLACEHOLDER} required />
              </Field>
            </div>
            {formError && <div className="md:col-span-2 text-sm text-status-critical">{formError}</div>}
            <div className="md:col-span-2">
              <Button type="submit" disabled={submitting}>{submitting ? 'Evaluating…' : 'Compute metrics'}</Button>
            </div>
          </form>
        </Card>
      )}

      {error !== null && <ApiErrorView error={error} />}
      {error === null && data === null && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No evaluations have been recorded yet." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            onRowClick={open}
            columns={[
              { header: 'Type', render: (r) => <span className="capitalize">{r.kind}</span> },
              { header: 'Model', render: (r) => `${r.model_name ?? '--'}${r.model_version ? ` ${formatVersion(r.model_version)}` : ''}` },
              { header: 'Dataset', render: (r) => `${r.dataset_name} ${formatVersion(r.dataset_version)}` },
              { header: 'Data', render: (r) => <SyntheticBadge synthetic={r.is_synthetic} /> },
              { header: 'Status', render: (r) => <StatusPill status={r.status} /> },
              { header: 'Headline metrics', render: (r) => <span className="text-xs text-slate-400">{headline(r)}</span> },
              { header: 'Evaluated', render: (r) => new Date(r.evaluated_at).toLocaleString() },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
