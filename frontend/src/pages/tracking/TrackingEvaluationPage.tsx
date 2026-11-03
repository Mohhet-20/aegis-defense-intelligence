import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { Page, TrackerConfigDefaults, TrackingEvaluationRun } from '../../types/api'
import { useAuth } from '../../context/auth'
import { DataTable } from '../../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, inputClass } from '../../components/ui/Primitives'

export function TrackingEvaluationPage() {
  const { user } = useAuth()
  const [trackerDefaults, setTrackerDefaults] = useState<TrackerConfigDefaults | null>(null)
  const [trackerKey, setTrackerKey] = useState('')
  const [data, setData] = useState<Page<TrackingEvaluationRun> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)

  const canRun = user?.role === 'administrator' || user?.role === 'analyst'

  function load() {
    api.trackingEvaluation
      .list(undefined, 1, 20)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [])
  useEffect(() => {
    api.tracking.config().then((d) => {
      setTrackerDefaults(d)
      setTrackerKey(d.default_tracker_key)
    })
  }, [])

  async function handleRun() {
    setRunning(true)
    setError(null)
    try {
      await api.trackingEvaluation.run({ tracker_key: trackerKey || undefined })
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
        title="Tracking Evaluation Workspace"
        description="Custom-defined track-level precision/recall, identity switches, fragmentation, mostly-tracked/mostly-lost ratios, and mean association IoU against a deterministic SYNTHETIC fixture ('parallel' + 'crossing' sequences). HOTA/IDF1/MOTA are never computed -- see docs/ml/TRACKING_EVALUATION.md."
      />

      {canRun && (
        <Card className="mb-5 max-w-lg">
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Tracker">
              <select className={inputClass} value={trackerKey} onChange={(e) => setTrackerKey(e.target.value)}>
                {(trackerDefaults?.available_trackers ?? []).map((t) => (
                  <option key={t.tracker_key} value={t.tracker_key}>
                    {t.tracker_key} v{t.tracker_version}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Button onClick={handleRun} disabled={running}>
            {running ? 'Evaluating…' : 'Run evaluation'}
          </Button>
        </Card>
      )}

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No tracking evaluation runs yet." />}
      {data && data.items.length > 0 && (
        <DataTable
          rows={data.items}
          columns={[
            { header: 'Tracker', render: (r) => `${r.tracker_key} v${r.tracker_version}` },
            { header: 'Dataset', render: (r) => `${r.dataset_name}${r.is_synthetic ? ' (synthetic)' : ''}` },
            { header: 'Precision', render: (r) => r.track_precision.toFixed(3) },
            { header: 'Recall', render: (r) => r.track_recall.toFixed(3) },
            { header: 'ID switches', render: (r) => r.identity_switches },
            { header: 'Fragmentation', render: (r) => r.fragmentation_count },
            { header: 'Mostly tracked', render: (r) => `${(r.mostly_tracked_ratio * 100).toFixed(0)}%` },
            { header: 'Mostly lost', render: (r) => `${(r.mostly_lost_ratio * 100).toFixed(0)}%` },
            { header: 'Mean IoU', render: (r) => r.mean_association_iou.toFixed(3) },
            { header: 'Evaluated', render: (r) => new Date(r.evaluated_at).toLocaleString() },
          ]}
        />
      )}
    </div>
  )
}
