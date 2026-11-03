import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import { LeafletMap, type MapMarker, type MapView } from '../../components/geo/LeafletMap'
import type { GeoRecordType, GeospatialQueryResult, LocatedRecord } from '../../types/api'
import { Card, DataOriginBadge, EmptyState, ErrorState, Field, PageHeader, Spinner } from '../../components/ui/Primitives'

const RECORD_TYPES: GeoRecordType[] = ['event', 'sensor', 'observation', 'asset']

// Washington DC-ish default -- this project's own synthetic demo data
// clusters near here (see scripts/seed.py). An operator with real data
// would pan/zoom to their own area of interest; nothing here hardcodes
// a real-world area of operations.
const DEFAULT_CENTER: [number, number] = [38.9, -77.03]
const DEFAULT_ZOOM = 13

// A category is derived from a record's OWN reported fields -- never
// an inferred threat level. "unvalidated" covers a record with no
// location_origin recorded at all (every pre-Phase-7 write path);
// "uncertain" covers one with an informational quality finding
// (uncertainty unknown or stale) even though its coordinates are
// usable. Section 7: markers visually distinguish these, never hide
// the distinction behind one generic pin.
type MarkerCategory = 'validated' | 'derived' | 'estimated_inferred' | 'uncertain' | 'unvalidated' | 'synthetic'

function categorize(record: LocatedRecord): MarkerCategory {
  if (record.is_synthetic) return 'synthetic'
  if (record.quality_findings.length > 0) return 'uncertain'
  if (record.location_origin === 'validated') return 'validated'
  if (record.location_origin === 'derived') return 'derived'
  if (record.location_origin === 'estimated' || record.location_origin === 'inferred') return 'estimated_inferred'
  return 'unvalidated'
}

const CATEGORY_STYLE: Record<MarkerCategory, { color: string; label: string }> = {
  validated: { color: '#22c55e', label: 'Validated' },
  derived: { color: '#38bdf8', label: 'Derived' },
  estimated_inferred: { color: '#a78bfa', label: 'Estimated / inferred' },
  uncertain: { color: '#f59e0b', label: 'Uncertain / stale' },
  unvalidated: { color: '#94a3b8', label: 'Unvalidated (no recorded origin)' },
  synthetic: { color: '#f472b6', label: 'Synthetic demo data' },
}

// Lightweight proximity clustering -- groups markers that round to the
// same grid cell at the CURRENT zoom level into one cluster circle,
// rather than pulling in a separate clustering library whose React 19
// support is unproven. A cluster shows its count and expands to
// individual popups is not implemented here (a documented limit of
// this slice) -- clicking a cluster instead lists its members below
// the map, which keeps every record inspectable without silently
// hiding it.
function clusterRecords(items: LocatedRecord[], zoom: number) {
  const cellDegrees = Math.max(0.0005, 4 / Math.pow(2, zoom))
  const groups = new Map<string, LocatedRecord[]>()
  for (const item of items) {
    const key = `${Math.round(item.latitude / cellDegrees)}:${Math.round(item.longitude / cellDegrees)}`
    const group = groups.get(key)
    if (group) group.push(item)
    else groups.set(key, [item])
  }
  return Array.from(groups.values())
}

export function MapExplorerPage() {
  const [recordTypes, setRecordTypes] = useState<GeoRecordType[]>(RECORD_TYPES)
  const [result, setResult] = useState<GeospatialQueryResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [zoom, setZoom] = useState(DEFAULT_ZOOM)
  const [showList, setShowList] = useState(false)
  const [selectedCluster, setSelectedCluster] = useState<LocatedRecord[] | null>(null)
  const [bounds, setBounds] = useState<MapView | null>(null)

  const tileUrl = import.meta.env.VITE_MAP_TILE_URL as string | undefined
  const tileAttribution = (import.meta.env.VITE_MAP_TILE_ATTRIBUTION as string | undefined) ?? '&copy; OpenStreetMap contributors'
  const mapConfigured = Boolean(tileUrl)

  function loadViewport(b: MapView) {
    setError(null)
    api.geospatial
      .viewport({
        min_lat: b.south,
        max_lat: b.north,
        min_lon: b.west,
        max_lon: b.east,
        record_types: recordTypes,
        max_results: 500,
      })
      .then(setResult)
      .catch((e) => setError(e.message))
  }

  function handleViewChange(view: MapView) {
    setBounds(view)
    setZoom(view.zoom)
    loadViewport(view)
  }

  useEffect(() => {
    if (bounds) loadViewport(bounds)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordTypes])

  const clusters = useMemo(() => (result ? clusterRecords(result.items, zoom) : []), [result, zoom])
  const markers = useMemo<MapMarker[]>(
    () =>
      clusters.map((group, i) => {
        if (group.length === 1) {
          const r = group[0]
          const cat = categorize(r)
          return {
            key: `${r.record_type}-${r.record_id}`,
            lat: r.latitude,
            lon: r.longitude,
            radius: 7,
            color: CATEGORY_STYLE[cat].color,
            fillOpacity: 0.8,
            popup: {
              strong: true,
              lines: [
                r.title,
                r.record_type,
                `${r.latitude.toFixed(5)}, ${r.longitude.toFixed(5)} (${r.coordinate_reference_system})`,
                `Origin: ${r.location_origin ?? 'unrecorded'}`,
                `Uncertainty: ${r.location_uncertainty_m !== null ? `${r.location_uncertainty_m}m` : 'unknown'}`,
                `${new Date(r.timestamp).toLocaleString()} (${r.timestamp_type})`,
              ],
              note: r.is_synthetic ? 'Synthetic demonstration data' : undefined,
            },
          }
        }
        const centerLat = group.reduce((sum, r) => sum + r.latitude, 0) / group.length
        const centerLon = group.reduce((sum, r) => sum + r.longitude, 0) / group.length
        return {
          key: `cluster-${i}-${group.length}`,
          lat: centerLat,
          lon: centerLon,
          radius: 10 + Math.min(10, group.length),
          color: '#f8fafc',
          fillColor: '#334155',
          fillOpacity: 0.85,
          onClick: () => setSelectedCluster(group),
          popup: {
            strong: true,
            lines: [`${group.length} records at this location/zoom`],
            action: { label: 'List members below', onClick: () => setSelectedCluster(group) },
          },
        }
      }),
    [clusters],
  )

  function toggleType(t: GeoRecordType) {
    setRecordTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  }

  return (
    <div>
      <PageHeader
        title="Interactive Map Explorer"
        description="Server-side viewport queries only -- panning or zooming re-queries the backend for exactly what's visible, never a client-side filter over a full-dataset download. Markers are colored by the record's OWN recorded location origin and quality, never by an inferred threat level."
        actions={
          <button
            onClick={() => setShowList((s) => !s)}
            className="rounded-md border border-charcoal-600 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-charcoal-700/60"
          >
            {showList ? 'Show map' : 'Accessible list view'}
          </button>
        }
      />

      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
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
        <div className="flex flex-wrap gap-3 text-xs text-slate-400">
          {(Object.keys(CATEGORY_STYLE) as MarkerCategory[]).map((cat) => (
            <span key={cat} className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: CATEGORY_STYLE[cat].color }} />
              {CATEGORY_STYLE[cat].label}
            </span>
          ))}
        </div>
      </div>

      {error && <ErrorState message={error} />}

      {!mapConfigured && !showList && (
        <Card className="mb-4">
          <p className="text-sm text-slate-400">
            No map tile source is configured (set <code className="rounded-sm bg-charcoal-900 px-1 py-0.5 text-xs">VITE_MAP_TILE_URL</code> -- e.g. a self-hosted tile
            server, or a public provider's URL template per that provider's own usage policy). The map cannot render tiles without one, but every located record is
            still queryable below via the accessible list view.
          </p>
          <button onClick={() => setShowList(true)} className="mt-3 rounded-md bg-accent-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-400">
            Open accessible list view
          </button>
        </Card>
      )}

      {mapConfigured && !showList && (
        <div className="h-[560px] overflow-hidden rounded-lg border border-charcoal-600/60">
          <LeafletMap
            center={DEFAULT_CENTER}
            zoom={DEFAULT_ZOOM}
            tileUrl={tileUrl!}
            attribution={tileAttribution}
            markers={markers}
            onViewChange={handleViewChange}
          />
        </div>
      )}

      {selectedCluster && (
        <Card className="mt-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-200">Cluster members ({selectedCluster.length})</h3>
            <button onClick={() => setSelectedCluster(null)} className="text-xs text-slate-500 hover:text-slate-300">
              Close
            </button>
          </div>
          <RecordList items={selectedCluster} />
        </Card>
      )}

      {showList && (
        <Card>
          <h3 className="mb-2 text-sm font-semibold text-slate-200">Located records (accessible list alternative to the map)</h3>
          {result && result.items.length === 0 && <EmptyState message="No located records in the last-queried viewport. Pan the map view or widen record types." />}
          {result && result.items.length > 0 && <RecordList items={result.items} />}
          {!result && <Spinner />}
        </Card>
      )}

      {result && (
        <p className="mt-3 text-xs text-slate-500">
          {result.returned_count} of {result.total_matched} matched in view
          {result.truncated && ' (truncated -- narrow the view or filters to see the rest)'}; {result.missing_or_invalid_location_count} record(s) excluded for a
          present-but-invalid location.
        </p>
      )}
    </div>
  )
}

function RecordList({ items }: { items: LocatedRecord[] }) {
  return (
    <ul className="divide-y divide-charcoal-700/50">
      {items.map((r) => {
        const cat = categorize(r)
        return (
          <li key={`${r.record_type}-${r.record_id}`} className="flex items-center justify-between py-2 text-sm">
            <div>
              <span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: CATEGORY_STYLE[cat].color }} />
              <span className="mr-2 rounded-sm bg-charcoal-700 px-1.5 py-0.5 text-xs capitalize text-slate-400">{r.record_type}</span>
              <span className="text-slate-200">{r.title}</span>
              {r.is_synthetic && (
                <span className="ml-2">
                  <DataOriginBadge origin="synthetic_demo" />
                </span>
              )}
            </div>
            <div className="text-right text-xs text-slate-500">
              <div>{r.latitude.toFixed(4)}, {r.longitude.toFixed(4)}</div>
              <div>{new Date(r.timestamp).toLocaleString()}</div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
