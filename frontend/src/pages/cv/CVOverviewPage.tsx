import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { Card, ErrorState, PageHeader, Spinner, StatTile } from '../../components/ui/Primitives'

interface Counts {
  media: number
  models: number
  jobsRunning: number
  jobsFailed: number
  jobsCompleted: number
  evaluations: number
}

export function CVOverviewPage() {
  const [counts, setCounts] = useState<Counts | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      api.media.list(1, 1),
      api.cvModels.list(1, 1),
      api.inference.list({ page: 1, page_size: 1, status: 'running' }),
      api.inference.list({ page: 1, page_size: 1, status: 'failed' }),
      api.inference.list({ page: 1, page_size: 1, status: 'completed' }),
      api.evaluation.list(undefined, 1, 1),
    ])
      .then(([media, models, running, failed, completed, evaluations]) =>
        setCounts({
          media: media.total,
          models: models.total,
          jobsRunning: running.total,
          jobsFailed: failed.total,
          jobsCompleted: completed.total,
          evaluations: evaluations.total,
        }),
      )
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <ErrorState message={error} />
  if (!counts) return <Spinner />

  return (
    <div>
      <PageHeader
        title="Computer Vision Overview"
        description="Every figure below is a live aggregate query against the real database -- never a hardcoded number. See docs/architecture/COMPUTER_VISION_ARCHITECTURE.md."
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
        <StatTile label="Media Assets" value={counts.media} />
        <StatTile label="Registered CV Models" value={counts.models} />
        <StatTile label="Jobs Completed" value={counts.jobsCompleted} />
        <StatTile label="Jobs Running" value={counts.jobsRunning} />
        <StatTile label="Jobs Failed" value={counts.jobsFailed} />
        <StatTile label="Evaluation Runs" value={counts.evaluations} />
      </div>

      <Card className="mt-6">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">What this covers</h2>
        <p className="text-sm text-slate-400">
          Secure image/video upload (real file-signature validation, never a trusted filename), a model registry extending
          the core <code className="text-slate-300">ModelRecord</code> table, a deterministic mock detector plus a real
          OpenCV HOG+SVM person detector, bounded video frame sampling, detection postprocessing with real NMS, analyst
          review, and promotion of a <em>confirmed</em> detection into the Evidence layer. See{' '}
          <Link to="/cv/models" className="text-accent-400 hover:underline">
            the model registry
          </Link>{' '}
          for what is actually registered right now.
        </p>
        <p className="mt-2 text-sm text-slate-500">
          Explicitly not built: facial recognition, biometric identity matching, automated person identification,
          continuous real-time surveillance, cross-camera re-identification, or any hostile-intent classification -- see
          docs/security/MEDIA_UPLOAD_SECURITY.md.
        </p>
      </Card>
    </div>
  )
}
