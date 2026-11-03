import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type { AnnotationType, Page, Track, TrackAnnotation, TrackMotion, TrackObservation } from '../../types/api'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../../components/ui/Primitives'

const ANNOTATION_TYPES: AnnotationType[] = ['reviewed', 'possible_error', 'fragmented_track', 'false_association', 'uncertain_association', 'note']

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between border-b border-charcoal-700/50 py-2 text-sm last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  )
}

function TrajectoryPlot({ motion }: { motion: TrackMotion }) {
  if (motion.steps.length === 0) {
    return <p className="text-sm text-slate-500">Only one observation -- no motion between two points to plot.</p>
  }
  const points = [motion.steps[0].center_from_px, ...motion.steps.map((s) => s.center_to_px)]
  const xs = points.map((p) => p[0])
  const ys = points.map((p) => p[1])
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const padding = 12
  const viewW = 420, viewH = 260
  const spanX = Math.max(1, maxX - minX)
  const spanY = Math.max(1, maxY - minY)
  const scaleX = (viewW - 2 * padding) / spanX
  const scaleY = (viewH - 2 * padding) / spanY
  const scale = Math.min(scaleX, scaleY)
  const toSvg = (p: [number, number]) => [padding + (p[0] - minX) * scale, padding + (p[1] - minY) * scale]
  const svgPoints = points.map(toSvg)
  const pathD = svgPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ')

  return (
    <div>
      <svg width={viewW} height={viewH} viewBox={`0 0 ${viewW} ${viewH}`} className="rounded-md bg-charcoal-900">
        <path d={pathD} fill="none" stroke="#38bdf8" strokeWidth={2} />
        {svgPoints.map((p, i) => (
          <circle key={i} cx={p[0]} cy={p[1]} r={i === 0 || i === svgPoints.length - 1 ? 4 : 2.5} fill={i === 0 ? '#34d399' : i === svgPoints.length - 1 ? '#f87171' : '#38bdf8'} />
        ))}
      </svg>
      <p className="mt-2 text-xs text-slate-500">
        Green = first observed position, red = last. Image-space pixels on the source video's stored resolution only --
        {' '}{motion.unit_note}.
      </p>
    </div>
  )
}

export function TrackDetailPage() {
  const { trackId } = useParams<{ trackId: string }>()
  const { user } = useAuth()
  const [track, setTrack] = useState<Track | null>(null)
  const [motion, setMotion] = useState<TrackMotion | null>(null)
  const [observations, setObservations] = useState<Page<TrackObservation> | null>(null)
  const [annotations, setAnnotations] = useState<TrackAnnotation[]>([])
  const [page, setPage] = useState(1)
  const [error, setError] = useState<string | null>(null)

  const [annotationType, setAnnotationType] = useState<AnnotationType>('note')
  const [note, setNote] = useState('')
  const [supersedes, setSupersedes] = useState<string | null>(null)
  const [submittingAnnotation, setSubmittingAnnotation] = useState(false)
  const [annotationError, setAnnotationError] = useState<string | null>(null)

  const canAnnotate = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  useEffect(() => {
    if (!trackId) return
    api.tracks.get(trackId).then(setTrack).catch((e) => setError(e.message))
    api.tracks.motion(trackId).then(setMotion).catch(() => undefined)
    api.tracks.annotations(trackId).then(setAnnotations).catch(() => undefined)
  }, [trackId])

  useEffect(() => {
    if (!trackId) return
    api.tracks.observations(trackId, { page, page_size: 20 }).then(setObservations).catch((e) => setError(e.message))
  }, [trackId, page])

  async function handleAnnotate() {
    if (!trackId) return
    setSubmittingAnnotation(true)
    setAnnotationError(null)
    try {
      await api.tracks.annotate(trackId, { annotation_type: annotationType, note: note || undefined, supersedes_annotation_id: supersedes ?? undefined })
      const refreshed = await api.tracks.annotations(trackId)
      setAnnotations(refreshed)
      setNote('')
      setSupersedes(null)
    } catch (err) {
      setAnnotationError(err instanceof ApiError ? err.message : 'Annotation failed.')
    } finally {
      setSubmittingAnnotation(false)
    }
  }

  if (error) return <ErrorState message={error} />
  if (!track) return <Spinner />

  return (
    <div>
      <PageHeader
        title={`Track ${track.sequence_track_id}`}
        description={
          <>
            Job-local identity only -- unique within <span className="font-mono">{track.tracking_job_id.slice(0, 8)}</span>, never a
            real-world identity and never reused across a rerun. See docs/ml/TRACK_LIFECYCLE.md.
          </>
        }
      />

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Track metadata</h2>
          <Row label="Class label" value={track.class_label ?? '(unlabeled)'} />
          <Row label="State" value={<StatusPill status={track.state} />} />
          <Row label="Frame span" value={`${track.first_frame_index} – ${track.last_frame_index}`} />
          <Row label="Time span" value={`${track.first_timestamp_seconds.toFixed(2)}s – ${track.last_timestamp_seconds.toFixed(2)}s`} />
          <Row label="Matched observations" value={track.matched_observations_count} />
          <Row label="Missed frames" value={track.missed_frames_count} />
          <pre className="mt-2 overflow-x-auto rounded-md bg-charcoal-900 p-3 text-xs text-slate-400">{JSON.stringify(track.quality_summary, null, 2)}</pre>
        </Card>

        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Lifecycle timeline</h2>
          {track.lifecycle_events.length === 0 ? (
            <EmptyState message="No lifecycle transitions recorded." />
          ) : (
            <ul className="space-y-2 text-xs">
              {track.lifecycle_events.map((e, i) => (
                <li key={i} className="flex items-center justify-between border-b border-charcoal-700/50 pb-2 last:border-0">
                  <span className="text-slate-500">frame {e.frame_index} @ {e.timestamp_seconds.toFixed(2)}s</span>
                  <span className="text-slate-300">{e.from_state ?? '(new)'} → <StatusPill status={e.to_state} /></span>
                  <span className="max-w-[40%] truncate text-slate-500" title={e.reason}>{e.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="md:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Trajectory (image-space, pixels only)</h2>
          {!motion ? <Spinner /> : <TrajectoryPlot motion={motion} />}
          {motion && (
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-400 md:grid-cols-4">
              <span>Total path length: {motion.total_path_length_px.toFixed(1)}px</span>
              <span>Net displacement: {motion.net_displacement_px.toFixed(1)}px</span>
              <span>Missed sampled frames: {motion.missed_sampled_frame_count}</span>
              <span>Fragmentation: {motion.fragmentation_count}</span>
            </div>
          )}
        </Card>

        <Card className="md:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Observations</h2>
          {!observations && <Spinner />}
          {observations && observations.items.length === 0 && <EmptyState message="No observations." />}
          {observations && observations.items.length > 0 && (
            <>
              <DataTable
                rows={observations.items}
                columns={[
                  { header: 'Frame', render: (o) => o.frame_index },
                  { header: 'Timestamp', render: (o) => `${o.frame_timestamp_seconds.toFixed(2)}s` },
                  { header: 'Class', render: (o) => o.class_label },
                  { header: 'Confidence', render: (o) => `${(o.confidence * 100).toFixed(1)}%` },
                  { header: 'Association', render: (o) => o.association_method },
                  { header: 'Cost (1-IoU)', render: (o) => (o.association_cost !== null ? o.association_cost.toFixed(3) : '--') },
                ]}
              />
              <Pagination page={observations.page} pageSize={observations.page_size} total={observations.total} onPageChange={setPage} />
            </>
          )}
        </Card>

        <Card className="md:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Analyst annotations</h2>
          <p className="mb-3 text-xs text-slate-500">
            Never edits the track or its observations -- a correction creates a new annotation pointing back at the one it
            supersedes; the original is kept, only marked superseded.
          </p>
          {annotations.length === 0 ? (
            <EmptyState message="No annotations yet." />
          ) : (
            <ul className="mb-4 space-y-2 text-xs">
              {annotations.map((a) => (
                <li key={a.id} className={`rounded-md border p-2 ${a.superseded_at ? 'border-charcoal-700/60 opacity-60' : 'border-charcoal-600/60'}`}>
                  <div className="flex items-center justify-between">
                    <StatusPill status={a.annotation_type} />
                    <span className="text-slate-500">{new Date(a.created_at).toLocaleString()}</span>
                  </div>
                  {a.note && <p className="mt-1 text-slate-300">{a.note}</p>}
                  {a.superseded_at && <p className="mt-1 text-status-warning">Superseded {new Date(a.superseded_at).toLocaleString()}</p>}
                  {!a.superseded_at && canAnnotate && (
                    <button className="mt-1 text-accent-400 hover:underline" onClick={() => setSupersedes(a.id)}>
                      Correct this annotation
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {canAnnotate ? (
            <div className="grid gap-3 md:grid-cols-3">
              <Field label="Type">
                <select className={inputClass} value={annotationType} onChange={(e) => setAnnotationType(e.target.value as AnnotationType)}>
                  {ANNOTATION_TYPES.map((t) => (
                    <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
                  ))}
                </select>
              </Field>
              <Field label="Note (optional)">
                <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
              </Field>
              <div className="flex items-end gap-2">
                <Button onClick={handleAnnotate} disabled={submittingAnnotation}>
                  {submittingAnnotation ? 'Saving…' : supersedes ? 'Save correction' : 'Add annotation'}
                </Button>
                {supersedes && (
                  <Button variant="secondary" onClick={() => setSupersedes(null)}>
                    Cancel
                  </Button>
                )}
              </div>
            </div>
          ) : (
            <p className="text-xs text-slate-500">Analyst, investigator, or administrator role required to annotate.</p>
          )}
          {annotationError && <ErrorState message={annotationError} />}
        </Card>
      </div>

      <p className="mt-4 text-xs text-slate-500">
        <Link to="/tracking" className="text-accent-400 hover:underline">
          Back to Tracking Overview
        </Link>
      </p>
    </div>
  )
}
