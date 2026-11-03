import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import type { GeoRecordType, GeospatialQueryResult, LocatedRecord, TimeBucketCountsResult } from '../../types/api'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, inputClass } from '../../components/ui/Primitives'

const RECORD_TYPES: GeoRecordType[] = ['event', 'sensor', 'observation', 'asset']

function isoHoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 3600_000).toISOString().slice(0, 16)
}

export function TimelineExplorerPage() {
  const [recordTypes, setRecordTypes] = useState<GeoRecordType[]>(RECORD_TYPES)
  const [since, setSince] = useState(isoHoursAgo(24 * 7))
  const [until, setUntil] = useState(new Date().toISOString().slice(0, 16))
  const [result, setResult] = useState<GeospatialQueryResult | null>(null)
  const [buckets, setBuckets] = useState<TimeBucketCountsResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Historical playback -- steps through REAL stored records in
  // ascending time order. Nothing here interpolates a position between
  // two records or invents a timestamp; it is exactly
  // geo_timeline_service.query_timeline(ascending=True)'s own result,
  // walked one index at a time.
  const [playbackIndex, setPlaybackIndex] = useState(0)
  const [playing, setPlaying] = useState(false)

  function load() {
    setError(null)
    const sinceIso = new Date(since).toISOString()
    const untilIso = new Date(until).toISOString()
    Promise.all([
      api.geospatial.timeline({ since: sinceIso, until: untilIso, record_types: recordTypes, ascending: true, max_results: 500 }),
      api.geospatial.timeBuckets({ since: sinceIso, until: untilIso, bucket_seconds: 6 * 3600, record_types: recordTypes }),
    ])
      .then(([tl, b]) => {
        setResult(tl)
        setBuckets(b)
        setPlaybackIndex(0)
      })
      .catch((e) => setError(e.message))
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [])

  useEffect(() => {
    if (!playing || !result || result.items.length === 0) return
    const timer = setInterval(() => {
      setPlaybackIndex((i) => (i + 1 >= result.items.length ? 0 : i + 1))
    }, 1000)
    return () => clearInterval(timer)
  }, [playing, result])

  function toggleType(t: GeoRecordType) {
    setRecordTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  }

  const maxBucketCount = useMemo(() => (buckets ? Math.max(1, ...buckets.buckets.map((b) => b.count)) : 1), [buckets])
  const current: LocatedRecord | null = result && result.items.length > 0 ? result.items[playbackIndex] : null

  return (
    <div>
      <PageHeader
        title="Timeline Explorer"
        description="Historical playback steps through real, already-stored records in time order -- it never interpolates a position between two records, never invents an in-between timestamp, and is never presented as a live feed."
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Since">
          <input type="datetime-local" className={inputClass} value={since} onChange={(e) => setSince(e.target.value)} />
        </Field>
        <Field label="Until">
          <input type="datetime-local" className={inputClass} value={until} onChange={(e) => setUntil(e.target.value)} />
        </Field>
        <Field label="Record types">
          <div className="flex gap-2">
            {RECORD_TYPES.map((t) => (
              <button
                key={t}
                onClick={() => toggleType(t)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium capitalize ${
                  recordTypes.includes(t) ? 'bg-accent-500/15 text-accent-400' : 'bg-charcoal-800 text-slate-400 hover:bg-charcoal-700'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </Field>
        <Button onClick={load}>Query</Button>
      </div>

      {error && <ErrorState message={error} />}
      {!result && !error && <Spinner />}

      {buckets && (
        <Card className="mb-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-200">
            Record counts per 6-hour bucket {buckets.is_approximate && <span className="text-xs text-status-warning">(bounded sample -- not an exact total)</span>}
          </h3>
          {buckets.buckets.length === 0 && <p className="text-sm text-slate-500">No buckets in range.</p>}
          <div className="flex h-24 items-end gap-0.5">
            {buckets.buckets.map((b) => (
              <div
                key={b.bucket_start}
                title={`${new Date(b.bucket_start).toLocaleString()} - ${b.count} record(s)`}
                className="flex-1 rounded-t bg-accent-500/60"
                style={{ height: `${Math.max(2, (b.count / maxBucketCount) * 100)}%` }}
              />
            ))}
          </div>
        </Card>
      )}

      {result && result.items.length === 0 && <EmptyState message="No located records in this range." />}

      {result && result.items.length > 0 && (
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-200">
              Playback -- record {playbackIndex + 1} of {result.items.length}
            </h3>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setPlaybackIndex((i) => Math.max(0, i - 1))} disabled={playbackIndex === 0}>
                &larr; Step back
              </Button>
              <Button variant="secondary" onClick={() => setPlaying((p) => !p)}>
                {playing ? 'Pause' : 'Play'}
              </Button>
              <Button variant="secondary" onClick={() => setPlaybackIndex((i) => Math.min(result.items.length - 1, i + 1))} disabled={playbackIndex === result.items.length - 1}>
                Step forward &rarr;
              </Button>
            </div>
          </div>
          {current && (
            <div className="rounded-md border border-charcoal-700/60 bg-charcoal-900/50 p-4">
              <div className="text-sm font-medium text-slate-100">{current.title}</div>
              <div className="mt-1 text-xs capitalize text-slate-500">{current.record_type}</div>
              <div className="mt-2 text-xs text-slate-400">
                {current.latitude.toFixed(5)}, {current.longitude.toFixed(5)} -- {new Date(current.timestamp).toLocaleString()} ({current.timestamp_type})
              </div>
              {current.quality_findings.length > 0 && (
                <div className="mt-2 text-xs text-status-warning">Quality notes: {current.quality_findings.join(', ').replace(/_/g, ' ')}</div>
              )}
            </div>
          )}
          <input
            type="range"
            min={0}
            max={Math.max(0, result.items.length - 1)}
            value={playbackIndex}
            onChange={(e) => setPlaybackIndex(Number(e.target.value))}
            className="mt-4 w-full"
          />
        </Card>
      )}
    </div>
  )
}
