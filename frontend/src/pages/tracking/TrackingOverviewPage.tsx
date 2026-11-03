import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { Card, ErrorState, PageHeader, Spinner, StatTile } from '../../components/ui/Primitives'

interface Counts {
  jobsCompleted: number
  jobsFailed: number
  jobsRunning: number
  evaluations: number
}

export function TrackingOverviewPage() {
  const [counts, setCounts] = useState<Counts | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      api.tracking.list({ page: 1, page_size: 1, status: 'completed' }),
      api.tracking.list({ page: 1, page_size: 1, status: 'failed' }),
      api.tracking.list({ page: 1, page_size: 1, status: 'running' }),
      api.trackingEvaluation.list(undefined, 1, 1),
    ])
      .then(([completed, failed, running, evaluations]) =>
        setCounts({ jobsCompleted: completed.total, jobsFailed: failed.total, jobsRunning: running.total, evaluations: evaluations.total }),
      )
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <ErrorState message={error} />
  if (!counts) return <Spinner />

  return (
    <div>
      <PageHeader
        title="Tracking Overview"
        description="Temporary, sequence-scoped track IDs within one video's detection sequence -- never a real-world identity, never persistent across videos. See docs/architecture/OBJECT_TRACKING_ARCHITECTURE.md."
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatTile label="Tracking Jobs Completed" value={counts.jobsCompleted} />
        <StatTile label="Tracking Jobs Failed" value={counts.jobsFailed} />
        <StatTile label="Tracking Jobs Running" value={counts.jobsRunning} />
        <StatTile label="Evaluation Runs" value={counts.evaluations} />
      </div>

      <Card className="mt-6">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">What this covers</h2>
        <p className="text-sm text-slate-400">
          A reusable tracker interface with one deterministic, IoU + Hungarian-assignment baseline tracker
          (<code className="text-slate-300">iou_hungarian_v1</code>), explicit track lifecycle states (tentative / confirmed /
          missing / reacquired / ended / rejected), image-space-only motion analytics in pixels, and custom-defined tracking
          evaluation metrics against a deterministic synthetic fixture. Consumes real{' '}
          <Link to="/cv/jobs" className="text-accent-400 hover:underline">
            Phase 4 video_frame_analysis InferenceJob
          </Link>{' '}
          detections directly -- never a standalone demo.
        </p>
        <p className="mt-2 text-sm text-slate-500">
          Explicitly not built: facial recognition, biometric identification, cross-camera identity matching, autonomous
          targeting or weapon control, or automatic hostile-intent classification. HOTA/IDF1/MOTA are never computed -- see
          docs/ml/TRACKING_EVALUATION.md.
        </p>
      </Card>
    </div>
  )
}
