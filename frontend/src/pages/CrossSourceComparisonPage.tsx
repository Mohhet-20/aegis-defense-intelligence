import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { CrossSourceComparison, Observation, Page, Sensor } from '../types/api'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

export function CrossSourceComparisonPage() {
  const { user } = useAuth()
  const [sensors, setSensors] = useState<Sensor[]>([])
  const [sensorAId, setSensorAId] = useState('')
  const [sensorBId, setSensorBId] = useState('')
  const [obsA, setObsA] = useState<Page<Observation> | null>(null)
  const [obsB, setObsB] = useState<Page<Observation> | null>(null)
  const [selectedA, setSelectedA] = useState('')
  const [selectedB, setSelectedB] = useState('')
  const [tolerance, setTolerance] = useState<number | ''>('')
  const [comparison, setComparison] = useState<CrossSourceComparison | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [linkResult, setLinkResult] = useState<string | null>(null)

  const canLink = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  useEffect(() => {
    api.sensors.list({ page_size: 100 }).then((d) => setSensors(d.items)).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!sensorAId) { setObsA(null); return }
    api.observations.list({ sensor_id: sensorAId, page_size: 20 }).then(setObsA).catch(() => setObsA(null))
  }, [sensorAId])

  useEffect(() => {
    if (!sensorBId) { setObsB(null); return }
    api.observations.list({ sensor_id: sensorBId, page_size: 20 }).then(setObsB).catch(() => setObsB(null))
  }, [sensorBId])

  async function handleCompare() {
    if (!selectedA || !selectedB) return
    setBusy(true)
    setError(null)
    setLinkResult(null)
    try {
      const result = await api.crossSourceComparison.compare(selectedA, selectedB, tolerance === '' ? undefined : tolerance)
      setComparison(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Comparison failed.')
    } finally {
      setBusy(false)
    }
  }

  async function handleCreateLink() {
    if (!selectedA || !selectedB) return
    setBusy(true)
    setError(null)
    try {
      const relationship = await api.crossSourceComparison.createLink(selectedA, selectedB, tolerance === '' ? undefined : tolerance)
      setLinkResult(`Saved as a reviewable EvidenceRelationship (${relationship.review_status}). This never merges the two observations into one value -- an analyst's own review decides what it means.`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the comparison link.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Cross-Source Comparison"
        description="Compares two observations from different sensors -- never merges them into one authoritative value, and a correlated timestamp is never treated as proof of causation or of describing the same real-world event."
      />

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Observation A</h2>
          <Field label="Sensor">
            <select className={inputClass} value={sensorAId} onChange={(e) => { setSensorAId(e.target.value); setSelectedA('') }}>
              <option value="">Select a sensor</option>
              {sensors.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
          {obsA && obsA.items.length === 0 && <EmptyState message="No observations for this sensor." />}
          {obsA && obsA.items.length > 0 && (
            <div className="mt-3">
              <Field label="Observation">
                <select className={inputClass} value={selectedA} onChange={(e) => setSelectedA(e.target.value)}>
                  <option value="">Select an observation</option>
                  {obsA.items.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.observation_type}: {o.measurement_value ?? '(no value)'} {o.unit ?? ''} @ {new Date(o.observed_at).toLocaleString()}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          )}
        </Card>

        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Observation B</h2>
          <Field label="Sensor">
            <select className={inputClass} value={sensorBId} onChange={(e) => { setSensorBId(e.target.value); setSelectedB('') }}>
              <option value="">Select a sensor</option>
              {sensors.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
          {obsB && obsB.items.length === 0 && <EmptyState message="No observations for this sensor." />}
          {obsB && obsB.items.length > 0 && (
            <div className="mt-3">
              <Field label="Observation">
                <select className={inputClass} value={selectedB} onChange={(e) => setSelectedB(e.target.value)}>
                  <option value="">Select an observation</option>
                  {obsB.items.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.observation_type}: {o.measurement_value ?? '(no value)'} {o.unit ?? ''} @ {new Date(o.observed_at).toLocaleString()}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          )}
        </Card>
      </div>

      <Card className="mt-4">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Tolerance (optional -- same unit as A)">
            <input type="number" step="any" min={0} className={inputClass} value={tolerance} onChange={(e) => setTolerance(e.target.value === '' ? '' : Number(e.target.value))} />
          </Field>
          <Button onClick={handleCompare} disabled={!selectedA || !selectedB || busy}>Compare</Button>
          {canLink && (
            <Button variant="secondary" onClick={handleCreateLink} disabled={!selectedA || !selectedB || busy}>
              Save as reviewable link
            </Button>
          )}
        </div>
        {error && <div className="mt-3"><ErrorState message={error} /></div>}
        {linkResult && <p className="mt-3 text-sm text-status-good">{linkResult}</p>}
      </Card>

      {busy && !comparison && <Spinner />}

      {comparison && (
        <Card className="mt-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Comparison result</h2>
          <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
            <div><span className="text-slate-500">Same measurement type</span><div>{comparison.same_measurement_type ? 'yes' : 'no'}</div></div>
            <div><span className="text-slate-500">Units compatible</span><div>{comparison.units_compatible ? 'yes' : 'no'}</div></div>
            <div><span className="text-slate-500">Value A</span><div>{comparison.value_a ?? '(missing)'} {comparison.unit_a ?? ''}</div></div>
            <div><span className="text-slate-500">Value B</span><div>{comparison.value_b ?? '(missing)'} {comparison.unit_b ?? ''}</div></div>
            <div><span className="text-slate-500">B converted to A's unit</span><div>{comparison.value_b_converted_to_unit_a ?? '--'}</div></div>
            <div><span className="text-slate-500">Delta</span><div>{comparison.delta ?? '--'}</div></div>
            <div>
              <span className="text-slate-500">Conflicting</span>
              <div>{comparison.conflicting === null ? 'not assessed' : <StatusPill status={comparison.conflicting ? 'failed' : 'confirmed'} />}</div>
            </div>
            <div><span className="text-slate-500">Time gap</span><div>{comparison.time_gap_seconds.toFixed(1)}s</div></div>
          </div>
          <p className="mt-3 text-sm text-slate-300">{comparison.explanation}</p>
        </Card>
      )}
    </div>
  )
}
