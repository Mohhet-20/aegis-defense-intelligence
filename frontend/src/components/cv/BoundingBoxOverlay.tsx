import { useEffect, useRef, useState } from 'react'
import type { DetectionResult } from '../../types/api'

// Bounding boxes are stored (and received from
// the API) as 0..1 fractions of the image's width/height -- NEVER
// pixel coordinates -- specifically so this component can draw a
// correct overlay at whatever size the browser is actually rendering
// the image at right now, including after the window resizes. A
// ResizeObserver on the <img> itself (not just a window resize
// listener) is what makes this correct even when the image's displayed
// size changes for a reason that has nothing to do with the window --
// a sidebar collapsing, a different viewport breakpoint, etc.
export function BoundingBoxOverlay({
  src,
  alt,
  detections,
  onBoxClick,
  selectedId,
}: {
  src: string
  alt: string
  detections: DetectionResult[]
  onBoxClick?: (detection: DetectionResult) => void
  selectedId?: string | null
}) {
  const imgRef = useRef<HTMLImageElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

  useEffect(() => {
    const el = imgRef.current
    if (!el) return
    const update = () => setSize({ width: el.clientWidth, height: el.clientHeight })
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    return () => observer.disconnect()
  }, [src])

  const colorFor = (d: DetectionResult) => {
    if (d.review_status === 'confirmed') return '#34d399' // status-good
    if (d.review_status === 'rejected') return '#f87171' // status-critical, de-emphasized
    return '#38bdf8' // accent -- unreviewed
  }

  return (
    <div className="relative inline-block max-w-full">
      <img ref={imgRef} src={src} alt={alt} className="block max-w-full rounded-md" onLoad={() => {
        const el = imgRef.current
        if (el) setSize({ width: el.clientWidth, height: el.clientHeight })
      }} />
      {size.width > 0 && (
        <svg
          className="pointer-events-none absolute left-0 top-0"
          width={size.width}
          height={size.height}
          viewBox={`0 0 ${size.width} ${size.height}`}
        >
          {detections.map((d) => {
            const x = d.bbox_x_min * size.width
            const y = d.bbox_y_min * size.height
            const w = (d.bbox_x_max - d.bbox_x_min) * size.width
            const h = (d.bbox_y_max - d.bbox_y_min) * size.height
            const isSelected = d.id === selectedId
            return (
              <g key={d.id} className="pointer-events-auto cursor-pointer" onClick={() => onBoxClick?.(d)}>
                <rect
                  x={x}
                  y={y}
                  width={w}
                  height={h}
                  fill="none"
                  stroke={colorFor(d)}
                  strokeWidth={isSelected ? 3 : 2}
                  rx={3}
                />
                <text x={x + 3} y={Math.max(10, y - 4)} fill={colorFor(d)} fontSize={11} fontFamily="monospace">
                  {d.class_label} {(d.confidence * 100).toFixed(0)}%
                </text>
              </g>
            )
          })}
        </svg>
      )}
    </div>
  )
}
