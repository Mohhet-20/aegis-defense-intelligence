import { useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { Track, TrackMotion } from '../../types/api'
import { Button, Card, ErrorState, Field, PageHeader, StatusPill, inputClass } from '../../components/ui/Primitives'

interface Loaded {
  track: Track
  motion: TrackMotion
}

function ComparisonColumn({ label, loaded, error }: { label: string; loaded: Loaded | null; error: string | null }) {
  if (error) return <Card><ErrorState message={error} /></Card>
  if (!loaded) return <Card><p className="text-sm text-slate-500">{label}: enter a track ID and load it.</p></Card>
  const { track, motion } = loaded
  return (
    <Card>
      <h2 className="mb-2 text-sm font-semibold text-slate-200">{label}: {track.sequence_track_id}</h2>
      <dl className="space-y-1.5 text-sm">
        <div className="flex justify-between"><dt className="text-slate-500">Class</dt><dd className="text-slate-200">{track.class_label ?? '(unlabeled)'}</dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">State</dt><dd><StatusPill status={track.state} /></dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">Job</dt><dd className="font-mono text-xs text-slate-300">{track.tracking_job_id.slice(0, 8)}</dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">Frame span</dt><dd className="text-slate-200">{track.first_frame_index}–{track.last_frame_index}</dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">Matched observations</dt><dd className="text-slate-200">{track.matched_observations_count}</dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">Missed frames</dt><dd className="text-slate-200">{track.missed_frames_count}</dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">Total path length</dt><dd className="text-slate-200">{motion.total_path_length_px.toFixed(1)}px</dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">Net displacement</dt><dd className="text-slate-200">{motion.net_displacement_px.toFixed(1)}px</dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">Bbox area change</dt><dd className="text-slate-200">{motion.bbox_area_change_ratio !== null ? `${(motion.bbox_area_change_ratio * 100).toFixed(0)}%` : '--'}</dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">Fragmentation</dt><dd className="text-slate-200">{motion.fragmentation_count}</dd></div>
        <div className="flex justify-between"><dt className="text-slate-500">Missed sampled frames</dt><dd className="text-slate-200">{motion.missed_sampled_frame_count}</dd></div>
      </dl>
    </Card>
  )
}

export function TrackComparisonPage() {
  const [idA, setIdA] = useState('')
  const [idB, setIdB] = useState('')
  const [loadedA, setLoadedA] = useState<Loaded | null>(null)
  const [loadedB, setLoadedB] = useState<Loaded | null>(null)
  const [errorA, setErrorA] = useState<string | null>(null)
  const [errorB, setErrorB] = useState<string | null>(null)

  async function load(id: string, setLoaded: (l: Loaded) => void, setError: (e: string | null) => void) {
    if (!id) return
    setError(null)
    try {
      const [track, motion] = await Promise.all([api.tracks.get(id), api.tracks.motion(id)])
      setLoaded({ track, motion })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load track.')
    }
  }

  return (
    <div>
      <PageHeader
        title="Track Comparison"
        description="Compares two tracks side by side -- same job or different jobs. This never implies the two tracks are the same real-world object; it is purely a side-by-side read of two independent, job-scoped results."
      />

      <Card className="mb-5">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="flex items-end gap-2">
            <Field label="Track A ID">
              <input className={inputClass} value={idA} onChange={(e) => setIdA(e.target.value)} placeholder="track id" />
            </Field>
            <Button onClick={() => load(idA, setLoadedA, setErrorA)} disabled={!idA}>Load</Button>
          </div>
          <div className="flex items-end gap-2">
            <Field label="Track B ID">
              <input className={inputClass} value={idB} onChange={(e) => setIdB(e.target.value)} placeholder="track id" />
            </Field>
            <Button onClick={() => load(idB, setLoadedB, setErrorB)} disabled={!idB}>Load</Button>
          </div>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <ComparisonColumn label="Track A" loaded={loadedA} error={errorA} />
        <ComparisonColumn label="Track B" loaded={loadedB} error={errorB} />
      </div>
    </div>
  )
}
