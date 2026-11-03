import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type { InfrastructureAlert, Page } from '../../types/api'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import { Button, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../../components/ui/Primitives'

function formatDateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '--'
}

const ACKNOWLEDGEABLE = new Set(['open', 'reopened'])
const RESOLVABLE = new Set(['open', 'acknowledged', 'reopened'])
const REOPENABLE = new Set(['resolved'])

export function FleetAlertCenterPage() {
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState(searchParams.get('status') ?? '')
  const [severity, setSeverity] = useState(searchParams.get('severity') ?? '')
  const [deviceId, setDeviceId] = useState(searchParams.get('device_id') ?? '')
  const [data, setData] = useState<Page<InfrastructureAlert> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actingOn, setActingOn] = useState<string | null>(null)
  const [sweeping, setSweeping] = useState(false)

  const canManage = user?.role === 'administrator' || user?.role === 'analyst'

  async function handleSweep() {
    setSweeping(true)
    setActionError(null)
    try {
      const result = await api.infraAlerts.evaluateSweep()
      load()
      window.alert(
        `Evaluated ${result.evaluated_device_count} device(s); ${result.alerts_touched_count} alert(s) created/updated/auto-resolved.`,
      )
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Evaluation sweep failed.')
    } finally {
      setSweeping(false)
    }
  }

  function load() {
    api.infraAlerts
      .list({ page, page_size: 20, status: status || undefined, severity: severity || undefined, device_id: deviceId || undefined })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load infrastructure alerts.'))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, status, severity, deviceId])

  // Keep the URL in sync so links from the Fleet Overview page (e.g.
  // ?severity=critical) are reflected in the filter controls, and the
  // current filter state is shareable/bookmarkable.
  useEffect(() => {
    const next = new URLSearchParams()
    if (status) next.set('status', status)
    if (severity) next.set('severity', severity)
    if (deviceId) next.set('device_id', deviceId)
    setSearchParams(next, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, severity, deviceId])

  async function handleAction(alert: InfrastructureAlert, action: 'acknowledge' | 'resolve' | 'reopen') {
    setActingOn(alert.id)
    setActionError(null)
    try {
      const fn = action === 'acknowledge' ? api.infraAlerts.acknowledge : action === 'resolve' ? api.infraAlerts.resolve : api.infraAlerts.reopen
      await fn(alert.id)
      load()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : `Failed to ${action} alert.`)
    } finally {
      setActingOn(null)
    }
  }

  return (
    <div>
      <PageHeader
        title="Fleet Alerts"
        description="Infrastructure alerts raised against the edge device fleet -- presence loss, capability regressions, config drift, and similar automated findings. There is no background scheduler in this build: device-offline/stale detection only happens when this sweep runs (automatically on every health-report submission for a reporting device, or on demand below for the whole fleet including silent devices)."
        actions={
          canManage && (
            <Button variant="secondary" onClick={handleSweep} disabled={sweeping}>
              {sweeping ? 'Evaluating…' : 'Evaluate fleet now'}
            </Button>
          )
        }
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-4">
        <Field label="Status">
          <select className={inputClass} value={status} onChange={(e) => { setPage(1); setStatus(e.target.value) }}>
            <option value="">All</option>
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
            <option value="reopened">Reopened</option>
          </select>
        </Field>
        <Field label="Severity">
          <select className={inputClass} value={severity} onChange={(e) => { setPage(1); setSeverity(e.target.value) }}>
            <option value="">All</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="serious">Serious</option>
            <option value="critical">Critical</option>
          </select>
        </Field>
        <Field label="Device ID">
          <input className={inputClass} value={deviceId} onChange={(e) => { setPage(1); setDeviceId(e.target.value) }} placeholder="Filter by device ID" />
        </Field>
      </div>

      {actionError && <div className="mb-3"><ErrorState message={actionError} /></div>}

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No infrastructure alerts match these filters." />}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            columns={[
              { header: 'Title', render: (a) => <span className="text-slate-200">{a.title}</span> },
              { header: 'Severity', render: (a) => <StatusPill status={a.severity} /> },
              { header: 'Status', render: (a) => <StatusPill status={a.status} /> },
              {
                header: 'Device',
                render: (a) =>
                  a.device_id ? (
                    <Link to={`/edge/devices/${a.device_id}`} className="font-mono text-xs text-accent-400 hover:underline">
                      {a.device_id.slice(0, 8)}
                    </Link>
                  ) : (
                    '--'
                  ),
              },
              { header: 'Occurrences', render: (a) => a.occurrence_count },
              { header: 'Last evaluated', render: (a) => formatDateTime(a.last_evaluated_at) },
              { header: 'Explanation', render: (a) => <span className="text-xs text-slate-400">{a.explanation ?? '--'}</span> },
              ...(canManage
                ? [
                    {
                      header: 'Actions',
                      render: (a: InfrastructureAlert) => (
                        <div className="flex gap-2">
                          <Button
                            variant="secondary"
                            disabled={!ACKNOWLEDGEABLE.has(a.status) || actingOn === a.id}
                            onClick={() => handleAction(a, 'acknowledge')}
                          >
                            Acknowledge
                          </Button>
                          <Button
                            variant="primary"
                            disabled={!RESOLVABLE.has(a.status) || actingOn === a.id}
                            onClick={() => handleAction(a, 'resolve')}
                          >
                            Resolve
                          </Button>
                          <Button
                            variant="danger"
                            disabled={!REOPENABLE.has(a.status) || actingOn === a.id}
                            onClick={() => handleAction(a, 'reopen')}
                          >
                            Reopen
                          </Button>
                        </div>
                      ),
                    },
                  ]
                : []),
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
