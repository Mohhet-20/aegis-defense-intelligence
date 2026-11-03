import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { CVModel, EvaluationDataset, ModelEvaluationRun, Page } from '../../types/api'
import { useAuth } from '../../context/auth'
import { DataTable } from '../../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, inputClass } from '../../components/ui/Primitives'
import { formatVersion } from '../../utils/version'

const DATASETS: { value: EvaluationDataset; label: string; help: string }[] = [
  {
    value: 'coco_val2017_subset',
    label: 'Real photographs (COCO val2017 subset)',
    help: 'Public benchmark photos with human-labelled people and vehicles. Requires scripts/fetch_eval_data.py. A small public sample -- not a measure of performance in any operational setting.',
  },
  {
    value: 'synthetic_single_rectangle_fixture',
    label: 'Synthetic fixture (pipeline check)',
    help: 'Generated rectangles. Checks that the inference pipeline works end to end; says nothing about real-world accuracy.',
  },
]

interface PerClass {
  ground_truth: number
  tp: number
  fp: number
  fn: number
  ap50: number | null
  precision: number | null
  recall: number | null
  f1: number | null
}

// '--' = not computed: synthetic runs have one box per image, so AP is not measured on them.
const fmt = (v: unknown) => (typeof v === 'number' ? v.toFixed(3) : '--')

export function EvaluationWorkspacePage() {
  const { user } = useAuth()
  const [models, setModels] = useState<CVModel[]>([])
  const [modelId, setModelId] = useState('')
  const [dataset, setDataset] = useState<EvaluationDataset>('coco_val2017_subset')
  const [sampleCount, setSampleCount] = useState(200)
  const [data, setData] = useState<Page<ModelEvaluationRun> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)

  const canRun = user?.role === 'administrator' || user?.role === 'analyst'
  const modelName = useMemo(() => new Map(models.map((m) => [m.id, `${m.name} ${formatVersion(m.version)}`])), [models])
  const latestReal = data?.items.find((r) => !r.is_synthetic)

  function load() {
    api.evaluation
      .list(undefined, 1, 20)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [])
  useEffect(() => {
    api.cvModels.list(1, 50).then((d) => {
      setModels(d.items)
      const preferred = d.items.find((m) => m.adapter_key === 'ssd_mobilenet_v1_coco') ?? d.items[0]
      if (preferred) setModelId(preferred.id)
    })
  }, [])

  async function handleRun() {
    if (!modelId) return
    setRunning(true)
    setError(null)
    try {
      await api.evaluation.run({ model_record_id: modelId, sample_count: sampleCount, dataset })
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Evaluation run failed.')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Model Evaluation Workspace"
        description="Precision, recall, F1, mean IoU and AP@0.5 for a registered detector, computed on the server from the model's own output. Choose real benchmark photographs or the synthetic pipeline check; every result says which it used. See docs/ml/MODEL_EVALUATION.md."
      />

      {canRun && (
        <Card className="mb-5 max-w-2xl">
          <div className="grid gap-3 md:grid-cols-3">
            <Field label="Model">
              <select className={inputClass} value={modelId} onChange={(e) => setModelId(e.target.value)}>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name} {formatVersion(m.version)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Dataset">
              <select className={inputClass} value={dataset} onChange={(e) => setDataset(e.target.value as EvaluationDataset)}>
                {DATASETS.map((d) => (
                  <option key={d.value} value={d.value}>
                    {d.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Images">
              <input type="number" min={1} max={200} className={inputClass} value={sampleCount} onChange={(e) => setSampleCount(Number(e.target.value))} />
            </Field>
          </div>
          <p className="mb-3 mt-2 text-xs text-slate-500">{DATASETS.find((d) => d.value === dataset)?.help}</p>
          <Button onClick={handleRun} disabled={running || !modelId}>
            {running ? 'Evaluating…' : 'Run evaluation'}
          </Button>
        </Card>
      )}

      {latestReal && (
        <Card className="mb-5">
          <h2 className="text-sm font-semibold text-slate-200">
            Latest real-image result: {modelName.get(latestReal.model_record_id) ?? 'model'} on {latestReal.sample_count} photographs
          </h2>
          <p className="mb-3 mt-1 text-xs text-slate-500">
            {latestReal.dataset_name} {formatVersion(latestReal.dataset_version)} · IoU ≥ {latestReal.iou_match_threshold} · operating confidence{' '}
            {fmt(latestReal.metrics_detail.operating_confidence_threshold)} · mAP@0.5 {fmt(latestReal.metrics_detail.map50)} ·{' '}
            {fmt(latestReal.metrics_detail.mean_inference_ms_per_image)} ms/image
          </p>
          <DataTable
            rows={Object.entries((latestReal.metrics_detail.per_class ?? {}) as Record<string, PerClass>).map(([cls, v]) => ({ id: cls, cls, ...v }))}
            columns={[
              { header: 'Class', render: (r) => r.cls },
              { header: 'Labelled objects', render: (r) => r.ground_truth },
              { header: 'AP@0.5', render: (r) => fmt(r.ap50) },
              { header: 'Precision', render: (r) => fmt(r.precision) },
              { header: 'Recall', render: (r) => fmt(r.recall) },
              { header: 'F1', render: (r) => fmt(r.f1) },
              { header: 'TP / FP / FN', render: (r) => `${r.tp} / ${r.fp} / ${r.fn}` },
            ]}
          />
        </Card>
      )}

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No evaluation runs yet." />}
      {data && data.items.length > 0 && (
        <DataTable
          rows={data.items}
          columns={[
            { header: 'Model', render: (r) => modelName.get(r.model_record_id) ?? r.model_record_id.slice(0, 8) },
            {
              header: 'Data',
              render: (r) => (
                <span className={r.is_synthetic ? 'text-status-warning' : 'text-status-good'}>{r.is_synthetic ? 'synthetic' : 'real photos'}</span>
              ),
            },
            { header: 'Dataset', render: (r) => `${r.dataset_name} ${formatVersion(r.dataset_version)}` },
            { header: 'Images', render: (r) => r.sample_count },
            { header: 'mAP@0.5', render: (r) => fmt(r.metrics_detail.map50) },
            { header: 'Precision', render: (r) => r.precision.toFixed(3) },
            { header: 'Recall', render: (r) => r.recall.toFixed(3) },
            { header: 'F1', render: (r) => r.f1_score.toFixed(3) },
            { header: 'Evaluated', render: (r) => new Date(r.evaluated_at).toLocaleString() },
          ]}
        />
      )}
    </div>
  )
}
