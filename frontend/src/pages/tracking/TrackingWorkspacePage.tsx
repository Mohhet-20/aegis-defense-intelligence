import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type { InferenceJob, MediaAsset, Track, TrackerConfigDefaults, TrackingJob, TrackObservation } from '../../types/api'
import { TrackOverlay } from '../../components/cv/TrackOverlay'
import { DataTable } from '../../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../../components/ui/Primitives'

export function TrackingWorkspacePage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const canRun = user?.role === 'administrator' || user?.role === 'analyst'

  const [sourceJobs, setSourceJobs] = useState<InferenceJob[]>([])
  const [inferenceJobId, setInferenceJobId] = useState('')
  const [trackerDefaults, setTrackerDefaults] = useState<TrackerConfigDefaults | null>(null)
  const [trackerKey, setTrackerKey] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [job, setJob] = useState<TrackingJob | null>(null)
  const [media, setMedia] = useState<MediaAsset | null>(null)
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [tracks, setTracks] = useState<Track[]>([])
  const [frameObservations, setFrameObservations] = useState<TrackObservation[]>([])
  const [selectedTrackId, setSelectedTrackId] = useState<string | null>(null)

  useEffect(() => {
    // Only a completed video_frame_analysis job has detections worth
    // tracking (Section 3A) -- a single image_detection job has one
    // frame, so there is nothing to associate across frames.
    api.inference.list({ page: 1, page_size: 100, status: 'completed' }).then((d) => {
      const videoJobs = d.items.filter((j) => j.job_type === 'video_frame_analysis')
      setSourceJobs(videoJobs)
      if (videoJobs.length > 0) setInferenceJobId(videoJobs[0].id)
    })
    api.tracking.config().then((d) => {
      setTrackerDefaults(d)
      setTrackerKey(d.default_tracker_key)
    })
  }, [])

  async function handleSubmit() {
    if (!inferenceJobId) return
    setSubmitting(true)
    setError(null)
    try {
      const newJob = await api.tracking.submit({ inference_job_id: inferenceJobId, tracker_key: trackerKey || undefined })
      setJob(newJob)
      setSelectedTrackId(null)
      const [mediaAsset, trackPage] = await Promise.all([
        api.media.get(newJob.media_asset_id),
        api.tracking.tracks(newJob.id, { page_size: 100 }),
      ])
      setMedia(mediaAsset)
      setTracks(trackPage.items)
      const url = await api.media.contentUrl(newJob.media_asset_id)
      setVideoUrl(url)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Tracking submission failed.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleTimeUpdate(currentTimeSeconds: number) {
    if (!job || !media?.fps) return
    const frameIndex = Math.round(currentTimeSeconds * media.fps)
    try {
      const observations = await api.tracking.frameTracks(job.id, frameIndex)
      setFrameObservations(observations)
    } catch {
      // A frame outside the job's sampled range simply has nothing to
      // show -- never treated as an error worth surfacing to the user.
      setFrameObservations([])
    }
  }

  const trackLabel = (trackId: string) => {
    const t = tracks.find((tr) => tr.id === trackId)
    return t ? t.sequence_track_id : trackId.slice(0, 8)
  }

  return (
    <div>
      <PageHeader
        title="Tracking Workspace"
        description="Submit a completed video_frame_analysis job for tracking, then play the video back with per-frame track overlays -- drawn only for frames with a real, persisted observation, never interpolated."
      />

      <Card className="mb-5">
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Source video inference job">
            <select className={inputClass} value={inferenceJobId} onChange={(e) => setInferenceJobId(e.target.value)}>
              {sourceJobs.length === 0 && <option value="">No completed video_frame_analysis jobs yet</option>}
              {sourceJobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.id.slice(0, 8)} -- {j.frames_processed} frame(s), {j.detections_created} detection(s)
                </option>
              ))}
            </select>
          </Field>
          <Field label="Tracker">
            <select className={inputClass} value={trackerKey} onChange={(e) => setTrackerKey(e.target.value)}>
              {(trackerDefaults?.available_trackers ?? []).map((t) => (
                <option key={t.tracker_key} value={t.tracker_key}>
                  {t.tracker_key} v{t.tracker_version}
                </option>
              ))}
            </select>
          </Field>
          <div className="flex items-end">
            {canRun ? (
              <Button onClick={handleSubmit} disabled={submitting || !inferenceJobId}>
                {submitting ? 'Tracking…' : 'Run tracking'}
              </Button>
            ) : (
              <span className="text-xs text-slate-500">Analyst/administrator role required to run tracking.</span>
            )}
          </div>
        </div>
      </Card>

      {error && <ErrorState message={error} />}

      {job && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-200">
              Job <StatusPill status={job.status} />
            </h2>
            <p className="mb-3 text-xs text-slate-500">
              {job.tracker_key} v{job.tracker_version} · {job.tracks_created} track(s) created · {job.detections_considered} detection(s)
              considered {job.error_message ? `· ${job.error_message}` : ''}
            </p>
            {!videoUrl && <Spinner />}
            {videoUrl && (
              <TrackOverlay
                src={videoUrl}
                observations={frameObservations}
                trackLabelFor={trackLabel}
                allTrackIds={tracks.map((t) => t.id)}
                selectedTrackId={selectedTrackId}
                onTimeUpdate={handleTimeUpdate}
                onBoxClick={(o) => setSelectedTrackId(o.track_id)}
              />
            )}
          </Card>

          <Card>
            <h2 className="mb-2 text-sm font-semibold text-slate-200">Tracks</h2>
            {tracks.length === 0 ? (
              <EmptyState message="No tracks were created for this job." />
            ) : (
              <DataTable
                rows={tracks}
                onRowClick={(t) => navigate(`/tracking/tracks/${t.id}`)}
                columns={[
                  { header: 'ID', render: (t) => t.sequence_track_id },
                  { header: 'Class', render: (t) => t.class_label ?? '(unlabeled)' },
                  { header: 'State', render: (t) => <StatusPill status={t.state} /> },
                  { header: 'Frames', render: (t) => `${t.first_frame_index}–${t.last_frame_index}` },
                  { header: 'Observations', render: (t) => t.matched_observations_count },
                ]}
              />
            )}
          </Card>
        </div>
      )}
    </div>
  )
}
