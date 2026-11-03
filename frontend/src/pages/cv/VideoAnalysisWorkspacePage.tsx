import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { CVModel, DetectionResult, InferenceJob, MediaAsset } from '../../types/api'
import { useAuth } from '../../context/auth'
import { DataTable } from '../../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, StatusPill, inputClass } from '../../components/ui/Primitives'
import { formatVersion } from '../../utils/version'

export function VideoAnalysisWorkspacePage() {
  const { user } = useAuth()
  const [videos, setVideos] = useState<MediaAsset[]>([])
  const [models, setModels] = useState<CVModel[]>([])
  const [mediaId, setMediaId] = useState('')
  const [modelId, setModelId] = useState('')
  const [intervalSeconds, setIntervalSeconds] = useState(2.0)
  const [maxFrames, setMaxFrames] = useState(30)
  const [job, setJob] = useState<InferenceJob | null>(null)
  const [detections, setDetections] = useState<DetectionResult[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canRun = user?.role === 'administrator' || user?.role === 'analyst'

  useEffect(() => {
    api.media.list(1, 100, 'video').then((d) => {
      setVideos(d.items)
      if (d.items.length > 0) setMediaId(d.items[0].id)
    })
    api.cvModels.list(1, 50).then((d) => {
      const videoModels = d.items.filter((m) => m.supported_media_types.includes('video'))
      setModels(videoModels)
      if (videoModels.length > 0) setModelId(videoModels[0].id)
    })
  }, [])

  const selectedVideo = videos.find((v) => v.id === mediaId)

  async function handleSubmit() {
    if (!mediaId || !modelId) return
    setSubmitting(true)
    setError(null)
    try {
      const newJob = await api.inference.submit({
        media_asset_id: mediaId, model_record_id: modelId, job_type: 'video_frame_analysis',
        frame_sample_interval_seconds: intervalSeconds, max_frames: maxFrames,
      })
      setJob(newJob)
      const dets = newJob.status === 'completed' ? await api.inference.detections(newJob.id, 1, 200) : null
      setDetections(dets?.items ?? [])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Submission failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Video Analysis Workspace"
        description="Bounded, point-in-time frame sampling -- never continuous real-time surveillance and never cross-camera re-identification. See docs/ml/VIDEO_FRAME_ANALYSIS.md."
      />

      <Card className="mb-5">
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Video">
            <select className={inputClass} value={mediaId} onChange={(e) => setMediaId(e.target.value)}>
              {videos.length === 0 && <option value="">No videos uploaded yet</option>}
              {videos.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.declared_filename}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Model">
            <select className={inputClass} value={modelId} onChange={(e) => setModelId(e.target.value)}>
              {models.length === 0 && <option value="">No video-capable models registered</option>}
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} {formatVersion(m.version)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Sample interval (seconds)">
            <input type="number" min={0.1} step={0.1} className={inputClass} value={intervalSeconds} onChange={(e) => setIntervalSeconds(Number(e.target.value))} />
          </Field>
          <Field label="Max frames (server-clamped)">
            <input type="number" min={1} className={inputClass} value={maxFrames} onChange={(e) => setMaxFrames(Number(e.target.value))} />
          </Field>
        </div>
        {selectedVideo && (
          <p className="mt-2 text-xs text-slate-500">
            {selectedVideo.duration_seconds?.toFixed(1)}s · {selectedVideo.fps?.toFixed(1)}fps · {selectedVideo.frame_count} raw frames
            (never all loaded into memory at once -- only the sampled subset is decoded).
          </p>
        )}
        <div className="mt-3">
          {canRun ? (
            <Button onClick={handleSubmit} disabled={submitting || !mediaId || !modelId}>
              {submitting ? 'Analyzing…' : 'Run frame analysis'}
            </Button>
          ) : (
            <span className="text-xs text-slate-500">Analyst/administrator role required to run inference.</span>
          )}
        </div>
      </Card>

      {error && <ErrorState message={error} />}

      {job && (
        <Card>
          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-200">
            Job <StatusPill status={job.status} />
          </h2>
          <p className="mb-3 text-xs text-slate-500">
            {job.frames_processed} frame(s) sampled · {job.detections_created} detection(s) · {job.error_message ?? 'no errors'}
          </p>
          {detections.length === 0 ? (
            <EmptyState message="No detections in the sampled frames." />
          ) : (
            <DataTable
              rows={detections}
              columns={[
                { header: 'Frame #', render: (d) => d.frame_index },
                { header: 'Timestamp', render: (d) => `${d.frame_timestamp_seconds?.toFixed(2)}s` },
                { header: 'Class', render: (d) => d.class_label },
                { header: 'Confidence', render: (d) => `${(d.confidence * 100).toFixed(1)}%` },
                { header: 'Review', render: (d) => <StatusPill status={d.review_status} /> },
              ]}
            />
          )}
        </Card>
      )}
    </div>
  )
}
