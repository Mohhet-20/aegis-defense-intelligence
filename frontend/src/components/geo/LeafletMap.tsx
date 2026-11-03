import { useEffect, useRef } from 'react'
import L from 'leaflet'

// Thin React wrapper around plain Leaflet (BSD-2-Clause). It replaced
// react-leaflet, whose Hippocratic License 2.1 the project chose not to ship.
//
// Popups are built from DOM nodes with textContent -- never innerHTML --
// because marker titles come from user-supplied records.

export interface MapMarker {
  key: string
  lat: number
  lon: number
  radius: number
  color: string
  fillColor?: string
  fillOpacity: number
  /** Lines shown in the popup, in order; `strong` renders the first line bold. */
  popup: { lines: string[]; strong?: boolean; note?: string; action?: { label: string; onClick: () => void } }
  onClick?: () => void
}

export interface MapView {
  south: number
  west: number
  north: number
  east: number
  zoom: number
}

interface Props {
  center: [number, number]
  zoom: number
  tileUrl: string
  attribution: string
  markers: MapMarker[]
  onViewChange: (view: MapView) => void
  className?: string
}

function popupNode(p: MapMarker['popup']): HTMLElement {
  const root = document.createElement('div')
  root.className = 'text-sm'
  p.lines.forEach((line, i) => {
    const div = document.createElement('div')
    div.textContent = line
    div.className = i === 0 && p.strong ? 'font-semibold' : 'text-xs'
    root.appendChild(div)
  })
  if (p.note) {
    const note = document.createElement('div')
    note.className = 'mt-1 text-xs font-medium text-pink-600'
    note.textContent = p.note
    root.appendChild(note)
  }
  if (p.action) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'mt-1 text-xs text-blue-600 underline'
    button.textContent = p.action.label
    const handler = p.action.onClick
    button.addEventListener('click', () => handler())
    root.appendChild(button)
  }
  return root
}

export function LeafletMap({ center, zoom, tileUrl, attribution, markers, onViewChange, className }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)
  const viewChangeRef = useRef(onViewChange)
  viewChangeRef.current = onViewChange

  // Create the map once; tear it down on unmount.
  useEffect(() => {
    if (!containerRef.current) return
    const map = L.map(containerRef.current, { center, zoom })
    L.tileLayer(tileUrl, { attribution }).addTo(map)
    const layer = L.layerGroup().addTo(map)
    const report = () => {
      const b = map.getBounds()
      viewChangeRef.current({ south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast(), zoom: map.getZoom() })
    }
    map.on('moveend', report)
    mapRef.current = map
    layerRef.current = layer
    report()
    return () => {
      map.off('moveend', report)
      map.remove()
      mapRef.current = null
      layerRef.current = null
    }
    // Center/zoom/tiles are initial values; later changes are driven by the user panning.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tileUrl, attribution])

  // Redraw markers whenever the data changes.
  useEffect(() => {
    const layer = layerRef.current
    if (!layer) return
    layer.clearLayers()
    for (const m of markers) {
      const marker = L.circleMarker([m.lat, m.lon], {
        radius: m.radius,
        color: m.color,
        fillColor: m.fillColor ?? m.color,
        fillOpacity: m.fillOpacity,
      })
      marker.bindPopup(popupNode(m.popup))
      if (m.onClick) {
        const handler = m.onClick
        marker.on('click', () => handler())
      }
      marker.addTo(layer)
    }
  }, [markers])

  return <div ref={containerRef} className={className ?? 'h-full w-full'} data-testid="leaflet-map" />
}
