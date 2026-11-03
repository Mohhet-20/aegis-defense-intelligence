import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { AnomalyReviewStatus, ObservationAnomaly, Page, Sensor } from '../types/api'
import { Pagination } from '../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

const REVIEW_ACTIONS: AnomalyReviewStatus[] = ['confirmed_unusual', 'dismissed_normal', 'data_quality_issue']

export function AnomalyReviewPage() {
  const { user } = useAuth()
  const [data, setData] = useState<Page<ObservationAnomaly> | null>(null)
  const [page, setPage] = useState(1)
  const [sensorFilter, setSensorFilter] = useState('')
  const [reviewStatusFilter, setReviewStatusFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [sensors, setSensors] = useState<Sensor[]>([])
  const [error, setError] = useState<string | null>(null)
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({})
  const [busyId, setBusyId] = useState<string | null>(null)

  const canReview = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  function load() {
    api.sensorAnalytics
      .listAnomalies({ page, page_size: 20, sensor_id: sensorFilter || undefined, review_status: reviewStatusFilter || undefined, category: categoryFilter || undefined })
      .then((d) => { setData(d); setError(null) })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [page, sensorFilter, reviewStatusFilter, categoryFilter])
  useEffect(() => {
    api.sensors.list({ page_size: 100 }).then((d) => setSensors(d.items)).catch(() => undefined)
  }, [])

  async function handleReview(anomaly: ObservationAnomaly, status: AnomalyReviewStatus) {
    setBusyId(anomaly.id)
    try {
      await api.sensorAnalytics.reviewAnomaly(anomaly.id, status, noteDrafts[anomaly.id] || undefined)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Review failed.')
    } finally {
      setBusyId(null)
    }
  }

  const sensorName = (id: string) => sensors.find((s) => s.id === id)?.name ?? id.slice(0, 8)

  return (
    <div>
      <PageHeader
        title="Anomaly Review Center"
        description="Every candidate here is a statistical observation against a sensor's own recent history -- never an autonomous threat or hostility judgment. 'analyst_confirmed' and 'data_quality' categories are only ever set by an explicit review action below, never by the detection method itself."
      />

      <Card className="mb-4">
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Sensor">
            <select className={inputClass} value={sensorFilter} onChange={(e) => { setPage(1); setSensorFilter(e.target.value) }}>
              <option value="">All sensors</option>
              {sensors.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
          <Field label="Review status">
            <select className={inputClass} value={reviewStatusFilter} onChange={(e) => { setPage(1); setReviewStatusFilter(e.target.value) }}>
              <option value="">All</option>
              <option value="unreviewed">Unreviewed</option>
              <option value="confirmed_unusual">Confirmed unusual</option>
              <option value="dismissed_normal">Dismissed normal</option>
              <option value="data_quality_issue">Data quality issue</option>
            </select>
          </Field>
          <Field label="Category">
            <select className={inputClass} value={categoryFilter} onChange={(e) => { setPage(1); setCategoryFilter(e.target.value) }}>
              <option value="">All</option>
              <option value="statistical_deviation">Statistical deviation</option>
              <option value="data_quality">Data quality</option>
              <option value="sensor_health">Sensor health</option>
              <option value="analyst_confirmed">Analyst confirmed</option>
            </select>
          </Field>
        </div>
      </Card>

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No anomaly candidates match these filters." />}
      {data && data.items.length > 0 && (
        <>
          <ul className="space-y-3">
            {data.items.map((a) => (
              <li key={a.id}>
                <Card>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <span className="font-medium text-slate-200">{sensorName(a.sensor_id)}</span>
                      <span className="ml-2 text-slate-500">{a.measurement_type}</span>
                      <span className="ml-2 text-xs text-slate-500">via {a.detection_method}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusPill status={a.severity} />
                      <StatusPill status={a.category} />
                      <StatusPill status={a.review_status} />
                    </div>
                  </div>
                  <p className="mt-2 text-sm text-slate-300">{a.explanation}</p>
                  <p className="mt-1 text-xs text-slate-500">{new Date(a.created_at).toLocaleString()}</p>

                  {canReview && a.review_status === 'unreviewed' && (
                    <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-charcoal-700/50 pt-3">
                      <Field label="Review note (optional)">
                        <input
                          className={inputClass}
                          value={noteDrafts[a.id] ?? ''}
                          onChange={(e) => setNoteDrafts((d) => ({ ...d, [a.id]: e.target.value }))}
                          maxLength={2000}
                        />
                      </Field>
                      {REVIEW_ACTIONS.map((action) => (
                        <Button key={action} variant="secondary" disabled={busyId === a.id} onClick={() => handleReview(a, action)}>
                          {action.replace(/_/g, ' ')}
                        </Button>
                      ))}
                    </div>
                  )}
                  {a.review_note && <p className="mt-2 text-xs text-slate-500">Note: {a.review_note}</p>}
                </Card>
              </li>
            ))}
          </ul>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
