import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { AuditRecord, DescriptiveStatistics, Sensor, SensorHealth, SensorLifecycleStatus, TimeSeriesResponse } from '../types/api'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

const LIFECYCLE_TARGETS: SensorLifecycleStatus[] = ['active', 'maintenance', 'retired', 'registered']

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between border-b border-charcoal-700/50 py-2 text-sm last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  )
}

const QUALITY_STATUS_COLOR: Record<string, string> = {
  valid: '#34d399',
  valid_with_warnings: '#fbbf24',
  invalid: '#f87171',
  stale: '#fbbf24',
  duplicate: '#94a3b8',
  incomplete: '#f87171',
  out_of_range: '#fb923c',
}

// Hand-rolled SVG time-series chart -- no charting library is installed
// in this project (same constraint the TrajectoryPlot in
// TrackDetailPage.tsx worked under). Every point is colored by its own
// validation_status, so a quality issue is visible on the chart itself,
// not hidden behind an aggregate. Deterministic stride-downsampling (if
// any) is always disclosed via `aggregation_note` below the chart --
// never silently smoothed.
function TimeSeriesChart({ series }: { series: TimeSeriesResponse }) {
  const points = series.points.filter((p) => p.value !== null) as Array<TimeSeriesResponse['points'][number] & { value: number }>
  if (points.length === 0) {
    return <EmptyState message="No numeric observations in this window." />
  }
  const viewW = 760
  const viewH = 220
  const padding = 28
  const times = points.map((p) => new Date(p.observed_at).getTime())
  const values = points.map((p) => p.value)
  const minT = Math.min(...times), maxT = Math.max(...times)
  const minV = Math.min(...values), maxV = Math.max(...values)
  const spanT = Math.max(1, maxT - minT)
  const spanV = Math.max(1e-6, maxV - minV)
  const toX = (t: number) => padding + ((t - minT) / spanT) * (viewW - 2 * padding)
  const toY = (v: number) => viewH - padding - ((v - minV) / spanV) * (viewH - 2 * padding)
  const svgPoints = points.map((p) => ({ x: toX(new Date(p.observed_at).getTime()), y: toY(p.value), p }))
  const pathD = svgPoints.map((sp, i) => `${i === 0 ? 'M' : 'L'} ${sp.x.toFixed(1)} ${sp.y.toFixed(1)}`).join(' ')

  return (
    <div>
      <svg width="100%" height={viewH} viewBox={`0 0 ${viewW} ${viewH}`} className="rounded-md bg-charcoal-900">
        <line x1={padding} y1={viewH - padding} x2={viewW - padding} y2={viewH - padding} stroke="#334155" strokeWidth={1} />
        <line x1={padding} y1={padding} x2={padding} y2={viewH - padding} stroke="#334155" strokeWidth={1} />
        <path d={pathD} fill="none" stroke="#38bdf8" strokeWidth={1.5} />
        {svgPoints.map((sp, i) => (
          <circle key={i} cx={sp.x} cy={sp.y} r={3} fill={QUALITY_STATUS_COLOR[sp.p.validation_status] ?? '#38bdf8'}>
            <title>
              {new Date(sp.p.observed_at).toLocaleString()}: {sp.p.value}{sp.p.unit ? ` ${sp.p.unit}` : ''} ({sp.p.validation_status}
              {sp.p.quality_flags.length > 0 ? `, flags: ${sp.p.quality_flags.join(', ')}` : ''})
            </title>
          </circle>
        ))}
        <text x={padding} y={16} fill="#64748b" fontSize={11}>{maxV.toFixed(2)}</text>
        <text x={padding} y={viewH - padding - 4} fill="#64748b" fontSize={11}>{minV.toFixed(2)}</text>
      </svg>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
        {Object.entries(QUALITY_STATUS_COLOR).map(([status, color]) => (
          <span key={status} className="inline-flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
            {status.replace(/_/g, ' ')}
          </span>
        ))}
      </div>
      {series.aggregation_note && <p className="mt-2 text-xs text-status-warning">{series.aggregation_note}</p>}
      <p className="mt-1 text-xs text-slate-500">
        {series.returned_count} of {series.total_in_range} points in range shown, {new Date(series.since).toLocaleString()} – {new Date(series.until).toLocaleString()}.
      </p>
    </div>
  )
}

export function SensorDetailPage() {
  const { sensorId } = useParams<{ sensorId: string }>()
  const { user } = useAuth()
  const [sensor, setSensor] = useState<Sensor | null>(null)
  const [health, setHealth] = useState<SensorHealth | null>(null)
  const [history, setHistory] = useState<AuditRecord[]>([])
  const [measurementType, setMeasurementType] = useState<string | null>(null)
  const [series, setSeries] = useState<TimeSeriesResponse | null>(null)
  const [stats, setStats] = useState<DescriptiveStatistics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionBusy, setActionBusy] = useState(false)
  const [note, setNote] = useState('')

  const canManage = user?.role === 'administrator' || user?.role === 'analyst'

  const refreshHealth = useCallback(() => {
    if (!sensorId) return
    api.sensorAnalytics.health(sensorId).then(setHealth).catch(() => undefined)
  }, [sensorId])

  const loadCore = useCallback(() => {
    if (!sensorId) return
    api.sensors.get(sensorId).then((s) => {
      setSensor(s)
      // Keep the selected type only if this sensor has it (navigating between sensors
      // used to carry the previous sensor's type over and query a series that does not exist).
      setMeasurementType((prev) => (prev && s.measurement_types.includes(prev) ? prev : (s.measurement_types[0] ?? null)))
    }).catch((e) => setError(e.message))
    api.sensors.statusHistory(sensorId).then(setHistory).catch(() => undefined)
    refreshHealth()
  }, [sensorId, refreshHealth])

  useEffect(loadCore, [loadCore])

  useEffect(() => {
    if (!sensorId || !measurementType) return
    api.sensorAnalytics.timeseries(sensorId, { measurement_type: measurementType, max_points: 300 }).then(setSeries).catch(() => setSeries(null))
    api.sensorAnalytics.statistics(sensorId, { measurement_type: measurementType }).then(setStats).catch(() => setStats(null))
  }, [sensorId, measurementType])

  async function handleRecompute() {
    if (!sensorId) return
    setActionBusy(true)
    setActionError(null)
    try {
      const updated = await api.sensorAnalytics.recomputeHealth(sensorId)
      setHealth(updated)
      const refreshedSensor = await api.sensors.get(sensorId)
      setSensor(refreshedSensor)
      const refreshedHistory = await api.sensors.statusHistory(sensorId)
      setHistory(refreshedHistory)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Health recompute failed.')
    } finally {
      setActionBusy(false)
    }
  }

  async function handleTransition(newStatus: string) {
    if (!sensorId) return
    setActionBusy(true)
    setActionError(null)
    try {
      const updated = await api.sensors.transitionLifecycle(sensorId, newStatus, note || undefined)
      setSensor(updated)
      setNote('')
      const refreshedHistory = await api.sensors.statusHistory(sensorId)
      setHistory(refreshedHistory)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Lifecycle transition failed.')
    } finally {
      setActionBusy(false)
    }
  }

  async function handleRunAnomalyChecks() {
    if (!sensorId || !measurementType) return
    setActionBusy(true)
    setActionError(null)
    try {
      const result = await api.sensorAnalytics.runAnomalyChecks(sensorId, measurementType)
      refreshHealth()
      setActionError(
        result.created.length > 0
          ? `${result.created.length} new anomaly candidate(s) found -- review them from the Anomaly Review Center.`
          : 'No new anomaly candidates found for this measurement type.',
      )
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Anomaly check failed.')
    } finally {
      setActionBusy(false)
    }
  }

  if (error) return <ErrorState message={error} />
  if (!sensor) return <Spinner />

  return (
    <div>
      <PageHeader
        title={sensor.name}
        description={
          <>
            {sensor.sensor_type}{sensor.category ? ` / ${sensor.category}` : ''} -- <StatusPill status={sensor.lifecycle_status} /> (legacy status: <StatusPill status={sensor.status} />)
          </>
        }
      />

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Registry metadata</h2>
          <Row label="Manufacturer / model" value={`${sensor.manufacturer ?? '--'} / ${sensor.model_name ?? '--'}`} />
          <Row label="Measurement types" value={sensor.measurement_types.length > 0 ? sensor.measurement_types.join(', ') : '(unconfigured)'} />
          <Row label="Nominal sampling interval" value={sensor.nominal_sampling_interval_seconds ? `${sensor.nominal_sampling_interval_seconds}s` : '--'} />
          <Row label="Timezone" value={sensor.sensor_timezone} />
          <Row label="Last seen" value={sensor.last_seen_at ? new Date(sensor.last_seen_at).toLocaleString() : 'never'} />
          <Row label="Last ingestion success" value={sensor.last_ingestion_success_at ? new Date(sensor.last_ingestion_success_at).toLocaleString() : 'never'} />
          <Row label="Device-reported status" value={sensor.device_reported_status ?? '(none supplied)'} />
          {sensor.retired_at && <Row label="Retired at" value={new Date(sensor.retired_at).toLocaleString()} />}
        </Card>

        <Card>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-200">Health (four separate signals)</h2>
            {canManage && (
              <Button variant="secondary" onClick={handleRecompute} disabled={actionBusy}>
                Recompute
              </Button>
            )}
          </div>
          {!health ? (
            <Spinner />
          ) : (
            <>
              <Row label="Connectivity" value={<StatusPill status={health.connectivity.status} />} />
              <p className="pb-2 text-xs text-slate-500">{health.connectivity.explanation}</p>
              <Row label="Measurement quality" value={<StatusPill status={health.measurement_quality.status} />} />
              <p className="pb-2 text-xs text-slate-500">{health.measurement_quality.explanation}</p>
              <Row label="Anomaly status" value={`${health.anomaly_status.unresolved_count} unresolved`} />
              <p className="pb-2 text-xs text-slate-500">{health.anomaly_status.explanation}</p>
              <Row label="Device-reported" value={health.device_reported.status ?? '(none)'} />
              <p className="text-xs text-slate-500">A statistical observation, never an automatic threat/hostility judgment.</p>
            </>
          )}
        </Card>

        {canManage && (
          <Card className="md:col-span-2">
            <h2 className="mb-2 text-sm font-semibold text-slate-200">Lifecycle actions</h2>
            <p className="mb-3 text-xs text-slate-500">
              Moving to maintenance/retired is always an explicit analyst action -- never computed automatically. Retiring a sensor
              stops it accepting new observation batches; its historical data stays fully queryable.
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Note (optional)">
                <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
              </Field>
              {LIFECYCLE_TARGETS.filter((t) => t !== sensor.lifecycle_status).map((target) => (
                <Button key={target} variant={target === 'retired' ? 'danger' : 'secondary'} onClick={() => handleTransition(target)} disabled={actionBusy}>
                  → {target}
                </Button>
              ))}
            </div>
            {actionError && <p className="mt-3 text-sm text-status-warning">{actionError}</p>}
          </Card>
        )}

        <Card className="md:col-span-2">
          <div className="mb-2 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-slate-200">Time-series explorer</h2>
            {sensor.measurement_types.length > 0 && (
              <select className={inputClass + ' max-w-xs'} value={measurementType ?? ''} onChange={(e) => setMeasurementType(e.target.value)}>
                {sensor.measurement_types.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            )}
          </div>
          {sensor.measurement_types.length === 0 ? (
            <EmptyState message="This sensor has no configured measurement types yet." />
          ) : !series ? (
            <Spinner />
          ) : (
            <TimeSeriesChart series={series} />
          )}
          {measurementType && canManage && (
            <div className="mt-3">
              <Button variant="secondary" onClick={handleRunAnomalyChecks} disabled={actionBusy}>
                Run anomaly checks for "{measurementType}"
              </Button>
            </div>
          )}
        </Card>

        <Card className="md:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Descriptive statistics</h2>
          {!stats ? (
            <Spinner />
          ) : stats.insufficient_sample ? (
            <EmptyState message="Not enough valid observations in this window to compute statistics." />
          ) : (
            <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              <Row label="Valid / invalid" value={`${stats.valid_count} / ${stats.invalid_count}`} />
              <Row label="Min / max" value={`${stats.minimum?.toFixed(3)} / ${stats.maximum?.toFixed(3)}`} />
              <Row label="Mean / median" value={`${stats.mean?.toFixed(3)} / ${stats.median?.toFixed(3)}`} />
              <Row label="Stdev" value={stats.stdev_sample !== null ? stats.stdev_sample.toFixed(4) : '--'} />
              <Row label="Rate of change" value={stats.rate_of_change_per_second !== null ? `${stats.rate_of_change_per_second.toFixed(5)}/s` : '--'} />
              <Row label="Latest value" value={stats.latest_valid_value !== null ? `${stats.latest_valid_value} ${stats.unit ?? ''}` : '--'} />
              <Row label="Sampling gaps" value={stats.gap_summary ? `${stats.gap_summary.gap_count} gap(s)` : '--'} />
              <Row label="Max gap" value={stats.gap_summary?.max_gap_seconds !== null && stats.gap_summary?.max_gap_seconds !== undefined ? `${stats.gap_summary.max_gap_seconds.toFixed(0)}s` : '--'} />
            </div>
          )}
        </Card>

        <Card className="md:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Status history (audit trail)</h2>
          {history.length === 0 ? (
            <EmptyState message="No lifecycle changes recorded yet." />
          ) : (
            <ul className="space-y-2 text-xs">
              {history.map((h) => (
                <li key={h.id} className="flex items-center justify-between border-b border-charcoal-700/50 pb-2 last:border-0">
                  <span className="text-slate-300">{h.action}</span>
                  <span className="text-slate-500">
                    {String(h.context_metadata.previous_status ?? '')} → <StatusPill status={String(h.context_metadata.new_status ?? '?')} />
                  </span>
                  <span className="text-slate-500">{new Date(h.created_at).toLocaleString()}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <p className="mt-4 text-xs text-slate-500">
        <Link to="/sensors" className="text-accent-400 hover:underline">
          Back to Sensor Registry
        </Link>
        {' · '}
        <Link to="/sensors/ingestion" className="text-accent-400 hover:underline">
          Ingestion Monitor
        </Link>
        {' · '}
        <Link to="/sensors/anomalies" className="text-accent-400 hover:underline">
          Anomaly Review Center
        </Link>
      </p>
    </div>
  )
}
