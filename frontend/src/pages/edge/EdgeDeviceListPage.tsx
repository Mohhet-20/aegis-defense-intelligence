import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type { Device, DeviceRegistrationResult, FleetSite, Page } from '../../types/api'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import {
  Button,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  OneTimeSecretField,
  PageHeader,
  Spinner,
  StatusPill,
  inputClass,
} from '../../components/ui/Primitives'

function formatDateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '--'
}

function RegisterDeviceDialog({ onClose, onRegistered }: { onClose: () => void; onRegistered: () => void }) {
  const [deviceIdentifier, setDeviceIdentifier] = useState('')
  const [deviceName, setDeviceName] = useState('')
  const [deviceType, setDeviceType] = useState('')
  const [deploymentLabel, setDeploymentLabel] = useState('')
  const [capabilities, setCapabilities] = useState('')
  const [inferenceBackends, setInferenceBackends] = useState('')
  const [metadataNote, setMetadataNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<DeviceRegistrationResult | null>(null)

  async function handleSubmit() {
    setSubmitting(true)
    setError(null)
    try {
      const res = await api.devices.register({
        device_identifier: deviceIdentifier,
        device_name: deviceName,
        device_type: deviceType,
        deployment_label: deploymentLabel || undefined,
        capabilities: capabilities ? capabilities.split(',').map((c) => c.trim()).filter(Boolean) : [],
        inference_backends: inferenceBackends ? inferenceBackends.split(',').map((c) => c.trim()).filter(Boolean) : [],
        metadata_note: metadataNote || undefined,
      })
      setResult(res)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Device registration failed.')
    } finally {
      setSubmitting(false)
    }
  }

  function handleDone() {
    onRegistered()
    onClose()
  }

  if (result) {
    return (
      <Modal title="Device registered" onClose={handleDone}>
        <p className="mb-3 text-sm text-slate-300">
          <span className="font-medium text-slate-100">{result.device.device_name}</span> ({result.device.device_identifier}) is now
          registered with administrative status <StatusPill status={result.device.administrative_status} />.
        </p>
        <p className="mb-2 text-sm text-slate-400">This device's API key -- give this to the device operator now:</p>
        <OneTimeSecretField value={result.api_key} />
        <div className="mt-4 flex justify-end">
          <Button onClick={handleDone}>Done</Button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal title="Register device" onClose={onClose}>
      <div className="grid gap-3">
        <Field label="Device identifier">
          <input className={inputClass} value={deviceIdentifier} onChange={(e) => setDeviceIdentifier(e.target.value)} maxLength={100} placeholder="e.g. field-node-014" />
        </Field>
        <Field label="Device name">
          <input className={inputClass} value={deviceName} onChange={(e) => setDeviceName(e.target.value)} maxLength={200} placeholder="e.g. Forward Sensor Node 14" />
        </Field>
        <Field label="Device type">
          <input className={inputClass} value={deviceType} onChange={(e) => setDeviceType(e.target.value)} maxLength={50} placeholder="e.g. field_sensor_node" />
        </Field>
        <Field label="Deployment label (optional)">
          <input className={inputClass} value={deploymentLabel} onChange={(e) => setDeploymentLabel(e.target.value)} />
        </Field>
        <Field label="Capabilities (comma-separated, optional)">
          <input className={inputClass} value={capabilities} onChange={(e) => setCapabilities(e.target.value)} placeholder="e.g. video, audio" />
        </Field>
        <Field label="Inference backends (comma-separated, optional)">
          <input className={inputClass} value={inferenceBackends} onChange={(e) => setInferenceBackends(e.target.value)} placeholder="e.g. onnx_cpu" />
        </Field>
        <Field label="Note (optional)">
          <input className={inputClass} value={metadataNote} onChange={(e) => setMetadataNote(e.target.value)} maxLength={300} />
        </Field>
      </div>
      {error && <div className="mt-3"><ErrorState message={error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={handleSubmit} disabled={submitting || !deviceIdentifier || !deviceName || !deviceType}>
          {submitting ? 'Registering…' : 'Register device'}
        </Button>
      </div>
    </Modal>
  )
}

export function EdgeDeviceListPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [administrativeStatus, setAdministrativeStatus] = useState(searchParams.get('administrative_status') ?? '')
  const [connectivityState, setConnectivityState] = useState('')
  const [search, setSearch] = useState('')
  const [data, setData] = useState<Page<Device> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showRegister, setShowRegister] = useState(false)
  const [sites, setSites] = useState<FleetSite[]>([])

  // Client-side-only filters: the backend's list_devices_query (see
  // backend/app/services/device_service.py) does not currently accept
  // presence_state or site_id as server-side filter parameters, so
  // these two are applied to the current page's items only, after the
  // server-side-filtered/paginated page is fetched. The pagination
  // control below still reflects the server's total/page count for the
  // administrative_status/connectivity_state/search filters, not the
  // further-narrowed count these two produce.
  const [presenceState, setPresenceState] = useState(searchParams.get('presence_state') ?? '')
  const [siteId, setSiteId] = useState('')

  const canManageDevices = user?.role === 'administrator' || user?.role === 'analyst'

  function load() {
    api.devices
      .list({ page, page_size: 20, administrative_status: administrativeStatus || undefined, connectivity_state: connectivityState || undefined, search: search || undefined })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load devices.'))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, administrativeStatus, connectivityState, search])

  useEffect(() => {
    api.fleetSites
      .list()
      .then(setSites)
      .catch(() => setSites([]))
  }, [])

  const sitesById = new Map(sites.map((s) => [s.id, s]))
  const visibleItems = (data?.items ?? []).filter(
    (d) => (!presenceState || d.presence_state === presenceState) && (!siteId || d.site_id === siteId),
  )
  const isClientFiltered = Boolean(presenceState || siteId)

  return (
    <div>
      <PageHeader
        title="Edge Devices"
        description="The device registry for Phase 8's offline-first edge AI fleet -- registration, lifecycle, connectivity, and pending sync/conflict counts. This is the human/admin surface only; devices themselves submit over a separate device-authenticated protocol."
        actions={
          canManageDevices && (
            <Button onClick={() => setShowRegister(true)}>Register device</Button>
          )
        }
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-5">
        <Field label="Administrative status">
          <select className={inputClass} value={administrativeStatus} onChange={(e) => { setPage(1); setAdministrativeStatus(e.target.value) }}>
            <option value="">All</option>
            <option value="pending">Pending</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
            <option value="maintenance">Maintenance</option>
            <option value="decommissioned">Decommissioned</option>
            <option value="revoked">Revoked</option>
          </select>
        </Field>
        <Field label="Connectivity (self-report)">
          <select className={inputClass} value={connectivityState} onChange={(e) => { setPage(1); setConnectivityState(e.target.value) }}>
            <option value="">All</option>
            <option value="online">Online</option>
            <option value="offline">Offline</option>
            <option value="unknown">Unknown</option>
          </select>
        </Field>
        <Field label="Presence (this page only)">
          <select className={inputClass} value={presenceState} onChange={(e) => setPresenceState(e.target.value)}>
            <option value="">All</option>
            <option value="online">Online</option>
            <option value="stale">Stale</option>
            <option value="offline">Offline</option>
            <option value="unknown">Unknown</option>
          </select>
        </Field>
        <Field label="Site (this page only)">
          <select className={inputClass} value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            <option value="">All</option>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Search">
          <input className={inputClass} value={search} onChange={(e) => { setPage(1); setSearch(e.target.value) }} placeholder="Identifier or name" />
        </Field>
      </div>

      {isClientFiltered && (
        <p className="mb-3 text-xs text-slate-500">
          Presence and site are not server-side filters here -- they narrow only the devices already on this page, not the total/page count below.
        </p>
      )}

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No devices registered yet." />}
      {data && data.items.length > 0 && visibleItems.length === 0 && (
        <EmptyState message="No devices on this page match the presence/site filter." />
      )}
      {data && visibleItems.length > 0 && (
        <>
          <DataTable
            rows={visibleItems}
            onRowClick={(row) => navigate(`/edge/devices/${row.id}`)}
            columns={[
              { header: 'Identifier', render: (d) => <span className="font-mono text-xs">{d.device_identifier}</span> },
              { header: 'Name', render: (d) => d.device_name },
              { header: 'Type', render: (d) => d.device_type },
              { header: 'Site', render: (d) => (d.site_id ? sitesById.get(d.site_id)?.name ?? d.site_id : '--') },
              { header: 'Admin status', render: (d) => <StatusPill status={d.administrative_status} /> },
              {
                header: 'Presence',
                render: (d) => (
                  <div className="flex flex-col gap-0.5" title={`Device self-reported connectivity: ${d.connectivity_state}`}>
                    <StatusPill status={d.presence_state} />
                    <span className="text-[10px] text-slate-500">self-report: {d.connectivity_state}</span>
                  </div>
                ),
              },
              { header: 'Last seen', render: (d) => formatDateTime(d.last_seen_at) },
              { header: 'Last sync', render: (d) => formatDateTime(d.last_sync_at) },
              { header: 'Pending sync', render: (d) => d.pending_sync_count },
              { header: 'Unresolved conflicts', render: (d) => d.unresolved_conflict_count },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}

      {showRegister && <RegisterDeviceDialog onClose={() => setShowRegister(false)} onRegistered={load} />}
    </div>
  )
}
