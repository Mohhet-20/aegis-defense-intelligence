import { useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { GeoRecordType } from '../../types/api'
import { Button, Card, ErrorState, Field, PageHeader, inputClass } from '../../components/ui/Primitives'

const RECORD_TYPES: GeoRecordType[] = ['event', 'sensor', 'observation', 'asset']

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function ExportCenterPage() {
  const [recordTypes, setRecordTypes] = useState<GeoRecordType[]>(RECORD_TYPES)
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [maxFeatures, setMaxFeatures] = useState(1000)
  const [busy, setBusy] = useState<'geojson' | 'csv' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<string | null>(null)

  function toggleType(t: GeoRecordType) {
    setRecordTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  }

  async function handleExport(format: 'geojson' | 'csv') {
    setBusy(format)
    setError(null)
    setLastResult(null)
    try {
      const params = {
        record_types: recordTypes,
        since: since ? new Date(since).toISOString() : undefined,
        until: until ? new Date(until).toISOString() : undefined,
        max_features: maxFeatures,
      }
      const { blob, filename } = format === 'geojson' ? await api.geospatial.exportGeojson(params) : await api.geospatial.exportCsv(params)
      downloadBlob(blob, filename)
      setLastResult(`Downloaded ${filename} (${blob.size} bytes).`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `Could not export ${format.toUpperCase()}.`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <PageHeader
        title="Export Center"
        description="Bounded, authorization-aware export of located records as GeoJSON or CSV. Every export is capped server-side and reports when it was truncated -- never a silent partial export presented as complete. Requires the Geospatial Export permission (Administrator or Analyst)."
      />

      <Card className="max-w-xl">
        <div className="space-y-4">
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
          <div className="grid grid-cols-2 gap-3">
            <Field label="Since (optional)">
              <input type="datetime-local" className={inputClass} value={since} onChange={(e) => setSince(e.target.value)} />
            </Field>
            <Field label="Until (optional)">
              <input type="datetime-local" className={inputClass} value={until} onChange={(e) => setUntil(e.target.value)} />
            </Field>
          </div>
          <Field label="Max features (server hard-caps this regardless)">
            <input type="number" min={1} className={inputClass} value={maxFeatures} onChange={(e) => setMaxFeatures(Number(e.target.value))} />
          </Field>

          {error && <ErrorState message={error} />}
          {lastResult && <div className="rounded-md border border-status-good/30 bg-status-good/10 px-3 py-2 text-sm text-status-good">{lastResult}</div>}

          <div className="flex gap-2">
            <Button onClick={() => handleExport('geojson')} disabled={busy !== null || recordTypes.length === 0}>
              {busy === 'geojson' ? 'Exporting…' : 'Export GeoJSON'}
            </Button>
            <Button variant="secondary" onClick={() => handleExport('csv')} disabled={busy !== null || recordTypes.length === 0}>
              {busy === 'csv' ? 'Exporting…' : 'Export CSV'}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  )
}
