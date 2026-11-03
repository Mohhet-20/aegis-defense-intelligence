import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { CVModel, DetectionResult, InferenceJob, MediaAsset } from '../../types/api'
import { useAuth } from '../../context/auth'
import { BoundingBoxOverlay } from '../../components/cv/BoundingBoxOverlay'
import { Button, Card, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../../components/ui/Primitives'
import { formatVersion } from '../../utils/version'

export function ImageDetectionWorkspacePage() {
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const [images, setImages] = useState<MediaAsset[]>([])
  const [models, setModels] = useState<CVModel[]>([])
  const [mediaId, setMediaId] = useState(searchParams.get('media') ?? '')
  const [modelId, setModelId] = useState('')
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [job, setJob] = useState<InferenceJob | null>(null)
  const [detections, setDetections] = useState<DetectionResult[]>([])
  const [selectedDetection, setSelectedDetection] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [promoteTitle, setPromoteTitle] = useState('')

  const canRun = user?.role === 'administrator' || user?.role === 'analyst'
  const canReview = canRun || user?.role === 'investigator'

  useEffect(() => {
    api.media.list(1, 100, 'image').then((d) => {
      setImages(d.items)
      if (!mediaId && d.items.length > 0) setMediaId(d.items[0].id)
    })
    api.cvModels.list(1, 50).then((d) => {
      const imageModels = d.items.filter((m) => m.supported_media_types.includes('image'))
      setModels(imageModels)
      if (imageModels.length > 0) setModelId(imageModels[0].id)
    })
    // Deliberately a one-time mount effect: it reads the initial
    // mediaId (possibly seeded from the ?media= query param) only to
    // decide whether to auto-select the first image -- re-running this
    // on every later mediaId change would fight the user's own selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!mediaId) return
    let cancelled = false
    api.media.contentUrl(mediaId).then((url) => !cancelled && setImageUrl(url))
    return () => {
      cancelled = true
    }
  }, [mediaId])

  async function handleSubmit() {
    if (!mediaId || !modelId) return
    setSubmitting(true)
    setError(null)
    setActionMessage(null)
    try {
      const newJob = await api.inference.submit({ media_asset_id: mediaId, model_record_id: modelId, job_type: 'image_detection' })
      setJob(newJob)
      if (newJob.status === 'completed') {
        const dets = await api.inference.detections(newJob.id)
        setDetections(dets.items)
      } else {
        setDetections([])
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Submission failed.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleReview(detection: DetectionResult, status: 'confirmed' | 'rejected') {
    try {
      const updated = await api.detections.review(detection.id, status)
      setDetections((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
    } catch (err) {
      setActionMessage(err instanceof ApiError ? err.message : 'Review failed.')
    }
  }

  async function handlePromote(detection: DetectionResult) {
    if (!promoteTitle) return
    try {
      await api.detections.promoteToEvidence(detection.id, promoteTitle)
      setActionMessage(`Promoted detection ${detection.id.slice(0, 8)} to Evidence.`)
    } catch (err) {
      setActionMessage(err instanceof ApiError ? err.message : 'Promotion failed.')
    }
  }

  return (
    <div>
      <PageHeader
        title="Image Detection Workspace"
        description="Upload → model selection → inference → validated, bounding-box-overlaid results, with analyst review required before anything becomes Evidence."
      />

      <Card className="mb-5">
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Image">
            <select className={inputClass} value={mediaId} onChange={(e) => setMediaId(e.target.value)}>
              {images.length === 0 && <option value="">No images uploaded yet</option>}
              {images.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.declared_filename}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Model">
            <select className={inputClass} value={modelId} onChange={(e) => setModelId(e.target.value)}>
              {models.length === 0 && <option value="">No image-capable models registered</option>}
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} {formatVersion(m.version)} ({m.adapter_key})
                </option>
              ))}
            </select>
          </Field>
          <div className="flex items-end">
            {canRun ? (
              <Button onClick={handleSubmit} disabled={submitting || !mediaId || !modelId}>
                {submitting ? 'Running…' : 'Run detection'}
              </Button>
            ) : (
              <span className="text-xs text-slate-500">Analyst/administrator role required to run inference.</span>
            )}
          </div>
        </div>
      </Card>

      {error && <ErrorState message={error} />}
      {actionMessage && <div className="mb-4 text-sm text-slate-300">{actionMessage}</div>}

      {!imageUrl && !error && <Spinner />}

      <div className="grid gap-4 md:grid-cols-2">
        {imageUrl && (
          <Card>
            <h2 className="mb-2 text-sm font-semibold text-slate-200">Image with detections</h2>
            <BoundingBoxOverlay
              src={imageUrl}
              alt="Selected media"
              detections={detections}
              onBoxClick={(d) => setSelectedDetection(d.id)}
              selectedId={selectedDetection}
            />
          </Card>
        )}

        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">
            Job {job && <StatusPill status={job.status} />}
          </h2>
          {job && (
            <div className="mb-3 text-xs text-slate-500">
              {job.detections_created} detection(s) · {job.error_message ?? 'no errors'}
            </div>
          )}
          {detections.length === 0 && job && <p className="text-sm text-slate-500">No detections above the confidence threshold.</p>}
          <ul className="space-y-2">
            {detections.map((d) => (
              <li key={d.id} className={`rounded-md border p-2 text-xs ${selectedDetection === d.id ? 'border-accent-500' : 'border-charcoal-600/60'}`}>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-slate-300">
                    {d.class_label} — {(d.confidence * 100).toFixed(1)}%
                  </span>
                  <StatusPill status={d.review_status} />
                </div>
                {canReview && d.review_status === 'unreviewed' && (
                  <div className="mt-2 flex gap-2">
                    <Button variant="secondary" onClick={() => handleReview(d, 'confirmed')}>
                      Confirm
                    </Button>
                    <Button variant="danger" onClick={() => handleReview(d, 'rejected')}>
                      Reject
                    </Button>
                  </div>
                )}
                {canReview && d.review_status === 'confirmed' && (
                  <div className="mt-2 flex gap-2">
                    <input
                      className={inputClass}
                      placeholder="Evidence title"
                      value={promoteTitle}
                      onChange={(e) => setPromoteTitle(e.target.value)}
                    />
                    <Button onClick={() => handlePromote(d)} disabled={!promoteTitle}>
                      Promote to Evidence
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}
