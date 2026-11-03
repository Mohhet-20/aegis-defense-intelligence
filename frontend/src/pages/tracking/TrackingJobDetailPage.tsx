import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type { Page, Track, TrackingJob, TrackingJobSummary } from '../../types/api'
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

export function TrackingJobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [job, setJob] = useState<TrackingJob | null>(null)
  const [summary, setSummary] = useState<TrackingJobSummary | null>(null)
  const [tracks, setTracks] = useState<Page<Track> | null>(null)
  const [page, setPage] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [retryMessage, setRetryMessage] = useState<string | null>(null)

  const canRetry = user?.role === 'administrator' || user?.role === 'analyst'

  useEffect(() => {
    if (!jobId) return
    api.tracking.get(jobId).then(setJob).catch((e) => setError(e.message))
    api.tracking.summary(jobId).then(setSummary).catch(() => undefined)
  }, [jobId])

  useEffect(() => {
    if (!jobId) return
    api.tracking.tracks(jobId, { page, page_size: 20 }).then(setTracks).catch((e) => setError(e.message))
  }, [jobId, page])

  async function handleRetry() {
    if (!jobId) return
    setRetrying(true)
    setRetryMessage(null)
    try {
      const newJob = await api.tracking.retry(jobId)
      navigate(`/tracking/jobs/${newJob.id}`)
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
        title={`Tracking Job ${job.id.slice(0, 8)}`}
        description={
          <>
            <Link to="/tracking/jobs" className="text-accent-400 hover:underline">
              Tracking Job Monitor
            </Link>{' '}
            / job detail. Synchronous execution -- there is no "cancel" for an in-flight job because there is no separate
            in-flight state to cancel (same as every job table in this codebase); a <em>failed</em> job can be retried, up to a
            bounded retry limit.
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
          <Row label="Tracker" value={`${job.tracker_key} v${job.tracker_version}`} />
          <Row label="Status" value={<StatusPill status={job.status} />} />
          <Row label="Media asset" value={<span className="font-mono text-xs">{job.media_asset_id.slice(0, 8)}</span>} />
          <Row label="Source inference job" value={<Link className="font-mono text-xs text-accent-400 hover:underline" to={`/cv/jobs/${job.inference_job_id}`}>{job.inference_job_id.slice(0, 8)}</Link>} />
          <Row label="Started" value={job.started_at ? new Date(job.started_at).toLocaleString() : '--'} />
          <Row label="Finished" value={job.finished_at ? new Date(job.finished_at).toLocaleString() : '--'} />
          <Row label="Processing duration" value={job.processing_duration_seconds !== null ? `${job.processing_duration_seconds.toFixed(2)}s` : '--'} />
          <Row label="Retry count" value={job.retry_count} />
          {job.error_message && <Row label="Error" value={<span className="text-status-critical">{job.error_category}: {job.error_message}</span>} />}
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Run counts &amp; configuration</h2>
          <Row label="Frames considered" value={job.frames_considered} />
          <Row label="Frames processed" value={job.frames_processed} />
          <Row label="Detections considered" value={job.detections_considered} />
          <Row label="Tracks created" value={job.tracks_created} />
          <pre className="mt-2 overflow-x-auto rounded-md bg-charcoal-900 p-3 text-xs text-slate-400">{JSON.stringify(job.config, null, 2)}</pre>
        </Card>

        {summary && (
          <Card className="md:col-span-2">
            <h2 className="mb-2 text-sm font-semibold text-slate-200">Summary</h2>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {Object.entries(summary.tracks_by_state).map(([state, count]) => (
                <div key={state} className="rounded-md border border-charcoal-600/60 p-3 text-center">
                  <div className="text-lg font-semibold text-slate-100">{count}</div>
                  <StatusPill status={state} />
                </div>
              ))}
            </div>
            <Row label="Total tracks" value={summary.total_tracks} />
            <Row label="Total observations" value={summary.total_observations} />
            <Row label="Mean track duration" value={`${summary.mean_track_duration_seconds.toFixed(2)}s`} />
          </Card>
        )}

        <Card className="md:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Tracks</h2>
          {!tracks && <Spinner />}
          {tracks && tracks.items.length === 0 && <EmptyState message="No tracks for this job." />}
          {tracks && tracks.items.length > 0 && (
            <>
              <DataTable
                rows={tracks.items}
                onRowClick={(t) => navigate(`/tracking/tracks/${t.id}`)}
                columns={[
                  { header: 'ID', render: (t) => t.sequence_track_id },
                  { header: 'Class', render: (t) => t.class_label ?? '(unlabeled)' },
                  { header: 'State', render: (t) => <StatusPill status={t.state} /> },
                  { header: 'Frames', render: (t) => `${t.first_frame_index}–${t.last_frame_index}` },
                  { header: 'Observations', render: (t) => t.matched_observations_count },
                  { header: 'Missed frames', render: (t) => t.missed_frames_count },
                ]}
              />
              <Pagination page={tracks.page} pageSize={tracks.page_size} total={tracks.total} onPageChange={setPage} />
            </>
          )}
        </Card>
      </div>
    </div>
  )
}
