import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { DataSource, IngestionJob, Page, Sensor, SensorRawRecord } from '../types/api'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

export function SensorIngestionPage() {
  const { user } = useAuth()
  const [jobs, setJobs] = useState<Page<IngestionJob> | null>(null)
  const [page, setPage] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [sensors, setSensors] = useState<Sensor[]>([])
  const [sources, setSources] = useState<DataSource[]>([])

  const [sourceId, setSourceId] = useState('')
  const [sensorId, setSensorId] = useState('')
  const [measurementType, setMeasurementType] = useState('temperature_c')
  const [unit, setUnit] = useState('celsius')
  const [count, setCount] = useState(20)
  const [seed, setSeed] = useState(0)
  const [baseValue, setBaseValue] = useState(20)
  const [noiseAmplitude, setNoiseAmplitude] = useState(0.5)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitBusy, setSubmitBusy] = useState(false)

  const [selectedJob, setSelectedJob] = useState<IngestionJob | null>(null)
  const [records, setRecords] = useState<Page<SensorRawRecord> | null>(null)

  const canIngest = user?.role === 'administrator' || user?.role === 'analyst'

  function loadJobs() {
    api.sensorIngestion.list({ page, page_size: 20 }).then((d) => { setJobs(d); setError(null) }).catch((e) => setError(e.message))
  }

  useEffect(loadJobs, [page])
  useEffect(() => {
    api.sensors.list({ page_size: 100 }).then((d) => setSensors(d.items)).catch(() => undefined)
    api.sources.list(1, 100).then((d) => setSources(d.items)).catch(() => undefined)
  }, [])

  async function handleSubmitSynthetic(e: FormEvent) {
    e.preventDefault()
    setSubmitError(null)
    setSubmitBusy(true)
    try {
      const job = await api.sensorIngestion.submitSynthetic({
        source_id: sourceId, sensor_id: sensorId, measurement_type: measurementType, unit: unit || undefined,
        count, seed, base_value: baseValue, noise_amplitude: noiseAmplitude,
      })
      setSubmitError(`Submitted: accepted ${job.accepted_count}, rejected ${job.rejected_count}, duplicate ${job.duplicate_count}.`)
      loadJobs()
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : 'Submission failed.')
    } finally {
      setSubmitBusy(false)
    }
  }

  async function handleViewRecords(job: IngestionJob) {
    setSelectedJob(job)
    try {
      const page = await api.sensorIngestion.records(job.id, { page_size: 50 })
      setRecords(page)
    } catch {
      setRecords(null)
    }
  }

  async function handleRetry(job: IngestionJob) {
    try {
      await api.sensorIngestion.retry(job.id)
      loadJobs()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Retry failed.')
    }
  }

  return (
    <div>
      <PageHeader
        title="Sensor Ingestion Monitor"
        description="Every batch here -- synthetic or file-uploaded -- runs through the real ingestion pipeline: quality validation, duplicate detection, and canonical observation creation. A record is never silently dropped; a rejected record still leaves a quarantine RawRecord behind."
      />

      {canIngest && (
        <Card className="mb-5">
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Submit a deterministic synthetic batch</h2>
          <p className="mb-3 text-xs text-slate-500">
            Fully reproducible from (seed, count, base_value, noise_amplitude) -- never claimed as live sensor data.
          </p>
          <form onSubmit={handleSubmitSynthetic} className="grid gap-3 md:grid-cols-4">
            <Field label="Data source">
              <select className={inputClass} value={sourceId} onChange={(e) => setSourceId(e.target.value)} required>
                <option value="" disabled>Select a source</option>
                {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
            <Field label="Sensor">
              <select className={inputClass} value={sensorId} onChange={(e) => setSensorId(e.target.value)} required>
                <option value="" disabled>Select a sensor</option>
                {sensors.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
            <Field label="Measurement type">
              <input className={inputClass} value={measurementType} onChange={(e) => setMeasurementType(e.target.value)} required />
            </Field>
            <Field label="Unit (optional)">
              <input className={inputClass} value={unit} onChange={(e) => setUnit(e.target.value)} />
            </Field>
            <Field label="Count">
              <input type="number" min={1} max={2000} className={inputClass} value={count} onChange={(e) => setCount(Number(e.target.value))} />
            </Field>
            <Field label="Seed">
              <input type="number" className={inputClass} value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
            </Field>
            <Field label="Base value">
              <input type="number" step="any" className={inputClass} value={baseValue} onChange={(e) => setBaseValue(Number(e.target.value))} />
            </Field>
            <Field label="Noise amplitude">
              <input type="number" step="any" min={0} className={inputClass} value={noiseAmplitude} onChange={(e) => setNoiseAmplitude(Number(e.target.value))} />
            </Field>
            <div className="flex items-end">
              <Button type="submit" disabled={submitBusy}>{submitBusy ? 'Submitting…' : 'Submit batch'}</Button>
            </div>
          </form>
          {submitError && <p className="mt-3 text-sm text-slate-300">{submitError}</p>}
        </Card>
      )}

      {error && <ErrorState message={error} />}
      {!jobs && !error && <Spinner />}
      {jobs && jobs.items.length === 0 && <EmptyState message="No sensor ingestion batches yet." />}
      {jobs && jobs.items.length > 0 && (
        <>
          <DataTable
            rows={jobs.items}
            onRowClick={handleViewRecords}
            columns={[
              { header: 'Job type', render: (j) => j.job_type },
              { header: 'Status', render: (j) => <StatusPill status={j.status} /> },
              { header: 'Accepted', render: (j) => j.accepted_count },
              { header: 'Rejected', render: (j) => j.rejected_count },
              { header: 'Duplicate', render: (j) => j.duplicate_count },
              { header: 'Started', render: (j) => new Date(j.started_at).toLocaleString() },
              {
                header: 'Actions',
                render: (j) =>
                  canIngest && (j.status === 'failed' || j.status === 'completed_with_errors') ? (
                    <button className="text-accent-400 hover:underline" onClick={(e) => { e.stopPropagation(); handleRetry(j) }}>
                      Retry
                    </button>
                  ) : null,
              },
            ]}
          />
          <Pagination page={jobs.page} pageSize={jobs.page_size} total={jobs.total} onPageChange={setPage} />
        </>
      )}

      {selectedJob && (
        <Card className="mt-5">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-200">Records for job {selectedJob.id.slice(0, 8)}</h2>
            <button className="text-xs text-slate-500 hover:text-slate-300" onClick={() => setSelectedJob(null)}>Close</button>
          </div>
          {selectedJob.error_summary.length > 0 && (
            <ul className="mb-3 space-y-1 text-xs text-status-warning">
              {selectedJob.error_summary.slice(0, 10).map((e, i) => <li key={i}>{e.error}</li>)}
            </ul>
          )}
          {!records && <Spinner />}
          {records && records.items.length === 0 && <EmptyState message="No records for this job." />}
          {records && records.items.length > 0 && (
            <DataTable
              rows={records.items}
              columns={[
                { header: 'External ID', render: (r) => r.external_record_id ?? '--' },
                { header: 'Validation', render: (r) => <StatusPill status={r.validation_status} /> },
                { header: 'Duplicate', render: (r) => (r.is_duplicate ? 'yes' : 'no') },
                { header: 'Errors', render: (r) => (r.validation_errors.length > 0 ? r.validation_errors.map((e) => e.message).join('; ') : '--') },
                { header: 'Received', render: (r) => new Date(r.received_at).toLocaleString() },
              ]}
            />
          )}
        </Card>
      )}
    </div>
  )
}
