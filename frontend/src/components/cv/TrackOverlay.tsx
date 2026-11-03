import { useEffect, useRef, useState } from 'react'
import type { TrackObservation } from '../../types/api'

// Phase 5: the multi-track analogue of BoundingBoxOverlay --
// same ResizeObserver-on-the-media-element discipline, so the overlay
// stays correct under responsive resizing, but drawn over a <video>
// element instead of an <img>, and over MULTIPLE tracks' boxes for
// whichever frame is currently playing.
//
// There is deliberately no interpolation here: `observations` is
// whatever app/tracking the backend actually persisted for the CLOSEST
// sampled frame to the video's current playback position (computed by
// the caller from fps) -- if that exact frame has no observation for a
// track, no box is drawn for it this instant. This mirrors Section 7's
// "never silently interpolate a missing position into authoritative
// evidence" at the UI layer, not just the data layer.
const TRACK_COLORS = ['#38bdf8', '#34d399', '#f59e0b', '#a78bfa', '#f87171', '#2dd4bf', '#fb7185', '#c084fc']

function colorForTrack(trackId: string, allTrackIds: string[]): string {
  const idx = allTrackIds.indexOf(trackId)
  return TRACK_COLORS[idx % TRACK_COLORS.length]
}

export function TrackOverlay({
  src,
  observations,
  trackLabelFor,
  allTrackIds,
  selectedTrackId,
  onBoxClick,
  onTimeUpdate,
}: {
  src: string
  observations: TrackObservation[]
  trackLabelFor: (trackId: string) => string
  allTrackIds: string[]
  selectedTrackId?: string | null
  onBoxClick?: (observation: TrackObservation) => void
  onTimeUpdate?: (currentTimeSeconds: number) => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

  useEffect(() => {
    const el = videoRef.current
    if (!el) return
    const update = () => setSize({ width: el.clientWidth, height: el.clientHeight })
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    return () => observer.disconnect()
  }, [src])

  return (
    <div className="relative inline-block max-w-full">
      <video
        ref={videoRef}
        src={src}
        controls
        className="block max-w-full rounded-md"
        onLoadedMetadata={() => {
          const el = videoRef.current
          if (el) setSize({ width: el.clientWidth, height: el.clientHeight })
        }}
        onTimeUpdate={(e) => onTimeUpdate?.(e.currentTarget.currentTime)}
      />
      {size.width > 0 && (
        <svg
          className="pointer-events-none absolute left-0 top-0"
          width={size.width}
          height={size.height - 32 /* leave the native video controls strip unobstructed */}
          viewBox={`0 0 ${size.width} ${size.height - 32}`}
        >
          {observations.map((o) => {
            const x = o.bbox_x_min * size.width
            const y = o.bbox_y_min * (size.height - 32)
            const w = (o.bbox_x_max - o.bbox_x_min) * size.width
            const h = (o.bbox_y_max - o.bbox_y_min) * (size.height - 32)
            const color = colorForTrack(o.track_id, allTrackIds)
            const isSelected = o.track_id === selectedTrackId
            return (
              <g key={o.id} className="pointer-events-auto cursor-pointer" onClick={() => onBoxClick?.(o)}>
                <rect x={x} y={y} width={w} height={h} fill="none" stroke={color} strokeWidth={isSelected ? 3 : 2} rx={3} />
                <text x={x + 3} y={Math.max(10, y - 4)} fill={color} fontSize={11} fontFamily="monospace">
                  {trackLabelFor(o.track_id)}
                </text>
              </g>
            )
          })}
        </svg>
      )}
    </div>
  )
}
