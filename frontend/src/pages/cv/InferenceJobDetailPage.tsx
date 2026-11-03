import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type { CVModel, DetectionResult, InferenceJob, Page } from '../../types/api'
import { BoundingBoxOverlay } from '../../components/cv/BoundingBoxOverlay'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, PageHeader, Spinner, StatusPill } from '../../components/ui/Primitives'

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between border-b border-charcoal-700/50 py-2 text-sm last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  )
}

export function InferenceJobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [job, setJob] = useState<InferenceJob | null>(null)
  const [detections, setDetections] = useState<Page<DetectionResult> | null>(null)
  const [page, setPage] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [retryMessage, setRetryMessage] = useState<string | null>(null)
  const [model, setModel] = useState<CVModel | null>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)

  const canRetry = user?.role === 'administrator' || user?.role === 'analyst'

  useEffect(() => {
    if (!jobId) return
    api.inference.get(jobId).then(setJob).catch((e) => setError(e.message))
  }, [jobId])

  // The model's name, and for a single-image job the image itself, so the detections
  // can be drawn where they were found. Both are optional extras: the page works without them.
  const modelId = job?.model_record_id
  const imageMediaId = job?.job_type === 'image_detection' ? job.media_asset_id : null
  useEffect(() => {
    if (!modelId) return
    api.cvModels.get(modelId).then(setModel).catch(() => setModel(null))
  }, [modelId])
  useEffect(() => {
    if (!imageMediaId) return
    let url: string | null = null
    let cancelled = false
    api.media.contentUrl(imageMediaId).then((u) => {
      url = u
      if (cancelled) URL.revokeObjectURL(u)
      else setImageUrl(u)
    }).catch(() => setImageUrl(null))
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [imageMediaId])

  useEffect(() => {
    if (!jobId) return
    api.inference.detections(jobId, page, 50).then(setDetections).catch((e) => setError(e.message))
  }, [jobId, page])

  async function handleRetry() {
    if (!jobId) return
    setRetrying(true)
    setRetryMessage(null)
    try {
      const newJob = await api.inference.retry(jobId)
      navigate(`/cv/jobs/${newJob.id}`)
    } catch (err) {
      setRetryMessage(err instanceof ApiError ? err.message : 'Retry failed.')
    } finally {
      setRetrying(false)
    }
  }

  if (error) return <ErrorState message={error} />
  if (!job) return <Spinner />

  return (
    <div>
      <PageHeader
        title={`Inference Job ${job.id.slice(0, 8)}`}
        description={
          <>
            <Link to="/cv/jobs" className="text-accent-400 hover:underline">
              Inference Job Monitor
            </Link>{' '}
            / job detail
          </>
        }
        actions={
          canRetry &&
          job.status === 'failed' && (
            <Button onClick={handleRetry} disabled={retrying}>
              {retrying ? 'Retrying…' : 'Retry'}
            </Button>
          )
        }
      />
      {retryMessage && <ErrorState message={retryMessage} />}

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Job metadata</h2>
          <Row label="Type" value={job.job_type} />
          <Row label="Status" value={<StatusPill status={job.status} />} />
          <Row label="Media asset" value={<span className="font-mono text-xs">{job.media_asset_id.slice(0, 8)}</span>} />
          <Row label="Model" value={model ? <span>{model.name} <span className="text-xs text-slate-500">({model.adapter_key})</span></span> : <span className="font-mono text-xs">{job.model_record_id.slice(0, 8)}</span>} />
          <Row label="Started" value={job.started_at ? new Date(job.started_at).toLocaleString() : '--'} />
          <Row label="Finished" value={job.finished_at ? new Date(job.finished_at).toLocaleString() : '--'} />
          <Row label="Retry count" value={job.retry_count} />
          {job.error_message && <Row label="Error" value={<span className="text-status-critical">{job.error_message}</span>} />}
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Run parameters</h2>
          <pre className="overflow-x-auto rounded-md bg-charcoal-900 p-3 text-xs text-slate-400">{JSON.stringify(job.parameters, null, 2)}</pre>
          <Row label="Frames processed" value={job.frames_processed} />
          <Row label="Detections created" value={job.detections_created} />
        </Card>

        {imageUrl && detections && (
          <Card className="md:col-span-2">
            <h2 className="mb-2 text-sm font-semibold text-slate-200">Image with detections</h2>
            <BoundingBoxOverlay src={imageUrl} alt="Analysed image" detections={detections.items} />
            <p className="mt-2 text-xs text-slate-500">Model output is advisory: boxes are unreviewed until an analyst confirms or rejects them.</p>
          </Card>
        )}

        <Card className="md:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Detections</h2>
          {!detections && <Spinner />}
          {detections && detections.items.length === 0 && <EmptyState message="No detections for this job." />}
          {detections && detections.items.length > 0 && (
            <>
              <DataTable
                rows={detections.items}
                columns={[
                  { header: 'Frame', render: (d) => (d.frame_index ?? '(image)') },
                  { header: 'Class', render: (d) => d.class_label },
                  { header: 'Confidence', render: (d) => `${(d.confidence * 100).toFixed(1)}%` },
                  { header: 'Review', render: (d) => <StatusPill status={d.review_status} /> },
                ]}
              />
              <Pagination page={detections.page} pageSize={detections.page_size} total={detections.total} onPageChange={setPage} />
            </>
          )}
        </Card>
      </div>
    </div>
  )
}
