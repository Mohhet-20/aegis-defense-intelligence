import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type {
  AuditRecord,
  Device,
  DeviceAdministrativeStatus,
  DeviceCapability,
  DeviceConfigBaseline,
  DeviceConfigState,
  DeviceHealthReport,
  DeviceRegistrationResult,
  FleetSite,
  LifecyclePreview,
  Page,
  SyncRecord,
} from '../../types/api'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  OneTimeSecretField,
  PageHeader,
  Spinner,
  StatusPill,
  Tabs,
  inputClass,
} from '../../components/ui/Primitives'

type TabKey = 'overview' | 'capabilities' | 'config' | 'sync' | 'health' | 'audit'

// Lifecycle targets a human operator can send this device to. Mirrors
// backend/app/services/device_service.py's _ADMIN_ALLOWED_TRANSITIONS
// exactly -- this table is only used to disable illegal buttons up
// front; the backend is still the sole source of truth and is re-checked
// (via the lifecycle-preview call, then the action call itself) before
// anything actually changes.
type LifecycleTarget = 'active' | 'suspended' | 'maintenance' | 'decommissioned' | 'revoked'

const ADMIN_ALLOWED_TRANSITIONS: Record<DeviceAdministrativeStatus, LifecycleTarget[]> = {
  pending: ['active', 'revoked'],
  active: ['suspended', 'maintenance', 'decommissioned', 'revoked'],
  suspended: ['active', 'revoked'],
  maintenance: ['active', 'decommissioned', 'revoked'],
  decommissioned: ['revoked'],
  revoked: [],
}

function formatDateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '--'
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between border-b border-charcoal-700/50 py-2 text-sm last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  )
}

function BoolBadge({ value, trueLabel = 'Yes', falseLabel = 'No' }: { value: boolean; trueLabel?: string; falseLabel?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${
        value ? 'border-status-good/30 bg-status-good/15 text-status-good' : 'border-slate-500/30 bg-slate-500/15 text-slate-400'
      }`}
    >
      {value ? trueLabel : falseLabel}
    </span>
  )
}

function HealthyBadge({ value }: { value: boolean | null }) {
  if (value === null) {
    return (
      <span className="inline-flex items-center rounded-full border border-slate-500/30 bg-slate-500/15 px-2 py-0.5 text-xs font-medium text-slate-400">
        Never verified
      </span>
    )
  }
  return <BoolBadge value={value} trueLabel="Healthy" falseLabel="Unhealthy" />
}

async function performLifecycleTransition(deviceId: string, target: LifecycleTarget, reason?: string): Promise<Device> {
  switch (target) {
    case 'active':
      return api.devices.activate(deviceId, reason)
    case 'suspended':
      return api.devices.suspend(deviceId, reason)
    case 'maintenance':
      return api.devices.maintenance(deviceId, reason)
    case 'decommissioned':
      return api.devices.decommission(deviceId, reason)
    case 'revoked':
      return api.devices.revoke(deviceId, reason)
  }
}

const LIFECYCLE_META: Record<LifecycleTarget, { title: string; verb: string; variant: 'primary' | 'danger' }> = {
  active: { title: 'Activate device', verb: 'Activate', variant: 'primary' },
  suspended: { title: 'Suspend device', verb: 'Suspend', variant: 'danger' },
  maintenance: { title: 'Enter maintenance', verb: 'Enter maintenance', variant: 'danger' },
  decommissioned: { title: 'Decommission device', verb: 'Decommission', variant: 'danger' },
  revoked: { title: 'Revoke device', verb: 'Revoke', variant: 'danger' },
}

// Fetches a read-only lifecycle-preview before letting the operator
// confirm a (possibly consequential) transition --.
// Applies to every lifecycle button on this page, not just the two new
// Actions.
function LifecyclePreviewDialog({
  deviceId,
  target,
  onClose,
  onDone,
}: {
  deviceId: string
  target: LifecycleTarget
  onClose: () => void
  onDone: (device: Device) => void
}) {
  const [preview, setPreview] = useState<LifecyclePreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const meta = LIFECYCLE_META[target]

  useEffect(() => {
    api.devices
      .lifecyclePreview(deviceId, target)
      .then((p) => {
        setPreview(p)
        setPreviewError(null)
      })
      .catch((e) => setPreviewError(e instanceof ApiError ? e.message : 'Failed to load transition preview.'))
  }, [deviceId, target])

  async function handleConfirm() {
    setSubmitting(true)
    setError(null)
    try {
      const device = await performLifecycleTransition(deviceId, target, reason || undefined)
      onDone(device)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `Failed to ${meta.verb.toLowerCase()}.`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal title={meta.title} onClose={onClose}>
      {previewError && <ErrorState message={previewError} />}
      {!preview && !previewError && <Spinner />}
      {preview && (
        <>
          <p className="mb-3 text-sm text-slate-400">
            <span className="font-mono text-xs">{preview.current_status}</span> &rarr; <span className="font-mono text-xs">{preview.target_status}</span>
          </p>
          {!preview.is_legal && (
            <div className="mb-3">
              <ErrorState message="This transition is not currently legal from the device's status -- confirming will be rejected." />
            </div>
          )}
          {preview.is_legal && preview.is_consequential && preview.impact_notes.length > 0 && (
            <div className="mb-3 rounded-md border border-status-warning/40 bg-status-warning/10 p-3">
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-status-warning">This is a consequential action</div>
              <ul className="list-disc space-y-1 pl-4 text-sm text-slate-300">
                {preview.impact_notes.map((note, i) => (
                  <li key={i}>{note}</li>
                ))}
              </ul>
            </div>
          )}
          {preview.is_legal && !preview.is_consequential && (
            <p className="mb-3 text-sm text-slate-400">This is a lifecycle transition and will be recorded in the device's audit trail.</p>
          )}
          <Field label="Reason (optional)">
            <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} />
          </Field>
          {error && <div className="mt-3"><ErrorState message={error} /></div>}
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button variant={meta.variant} onClick={handleConfirm} disabled={submitting || !preview.is_legal}>
              {submitting ? `${meta.verb}ing…` : `Confirm ${meta.verb.toLowerCase()}`}
            </Button>
          </div>
        </>
      )}
    </Modal>
  )
}

function RotateKeyDialog({ deviceId, onClose }: { deviceId: string; onClose: () => void }) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<DeviceRegistrationResult | null>(null)

  useEffect(() => {
    setSubmitting(true)
    api.devices
      .rotateKey(deviceId)
      .then(setResult)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Key rotation failed.'))
      .finally(() => setSubmitting(false))
  }, [deviceId])

  return (
    <Modal title="Rotate API key" onClose={onClose}>
      {submitting && <Spinner />}
      {error && <ErrorState message={error} />}
      {result && (
        <>
          <p className="mb-2 text-sm text-slate-400">
            The device's previous key is now invalid. Give this new key to the device operator now:
          </p>
          <OneTimeSecretField value={result.api_key} />
        </>
      )}
      <div className="mt-4 flex justify-end">
        <Button onClick={onClose}>Done</Button>
      </div>
    </Modal>
  )
}

function AssignSiteDialog({
  deviceId,
  sites,
  currentSiteId,
  onClose,
  onDone,
}: {
  deviceId: string
  sites: FleetSite[]
  currentSiteId: string | null
  onClose: () => void
  onDone: (device: Device) => void
}) {
  const [siteId, setSiteId] = useState(currentSiteId ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleConfirm() {
    setSubmitting(true)
    setError(null)
    try {
      const device = await api.devices.assignSite(deviceId, siteId || null)
      onDone(device)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to assign site.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal title="Assign site" onClose={onClose}>
      <Field label="Site">
        <select className={inputClass} value={siteId} onChange={(e) => setSiteId(e.target.value)}>
          <option value="">No site</option>
          {sites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </Field>
      {error && <div className="mt-3"><ErrorState message={error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={handleConfirm} disabled={submitting}>
          {submitting ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </Modal>
  )
}

function OverviewTab({
  device,
  canManage,
  sites,
  onChanged,
}: {
  device: Device
  canManage: boolean
  sites: FleetSite[]
  onChanged: (d: Device) => void
}) {
  const [lifecycleAction, setLifecycleAction] = useState<LifecycleTarget | null>(null)
  const [showRotate, setShowRotate] = useState(false)
  const [showAssignSite, setShowAssignSite] = useState(false)

  const allowed = new Set(ADMIN_ALLOWED_TRANSITIONS[device.administrative_status] ?? [])
  const siteName = device.site_id ? sites.find((s) => s.id === device.site_id)?.name ?? device.site_id : null

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Device</h2>
        <Row label="Identifier" value={<span className="font-mono text-xs">{device.device_identifier}</span>} />
        <Row label="Name" value={device.device_name} />
        <Row label="Type" value={device.device_type} />
        <Row label="Deployment label" value={device.deployment_label ?? '--'} />
        <Row label="Site" value={siteName ?? 'Unassigned'} />
        <Row label="Administrative status" value={<StatusPill status={device.administrative_status} />} />
        <Row
          label="Presence"
          value={
            <span title={`Device self-reported connectivity: ${device.connectivity_state}`}>
              <StatusPill status={device.presence_state} />
            </span>
          }
        />
        <Row label="Connectivity (device self-report)" value={<StatusPill status={device.connectivity_state} />} />
        <Row label="Software version" value={device.software_version ?? '--'} />
        <Row label="Protocol version" value={device.protocol_version ?? '--'} />
        <Row label="API key prefix" value={device.api_key_prefix ? <span className="font-mono text-xs">{device.api_key_prefix}…</span> : '--'} />
        <Row label="Config version" value={device.config_version ?? '--'} />
        <Row label="Last seen" value={formatDateTime(device.last_seen_at)} />
        <Row label="Last sync" value={formatDateTime(device.last_sync_at)} />
        <Row label="Last health report" value={formatDateTime(device.last_health_report_at)} />
        <Row label="Pending sync count" value={device.pending_sync_count} />
        <Row label="Unresolved conflicts" value={device.unresolved_conflict_count} />
        {device.revoked_at && <Row label="Revoked" value={`${formatDateTime(device.revoked_at)} -- ${device.revoked_reason ?? 'no reason given'}`} />}
        {device.metadata_note && <Row label="Note" value={device.metadata_note} />}
        {canManage && (
          <div className="mt-3">
            <Button variant="secondary" onClick={() => setShowAssignSite(true)}>
              {siteName ? 'Change site' : 'Assign site'}
            </Button>
          </div>
        )}
      </Card>

      <Card>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Capabilities &amp; model manifest</h2>
        <Row label="Capabilities" value={device.capabilities.length ? device.capabilities.join(', ') : '--'} />
        <Row label="Inference backends" value={device.inference_backends.length ? device.inference_backends.join(', ') : '--'} />
        <pre className="mt-2 overflow-x-auto rounded-md bg-charcoal-900 p-3 text-xs text-slate-400">{JSON.stringify(device.model_manifest, null, 2)}</pre>
        {device.local_storage_status && (
          <>
            <h3 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Local storage status</h3>
            <pre className="overflow-x-auto rounded-md bg-charcoal-900 p-3 text-xs text-slate-400">{JSON.stringify(device.local_storage_status, null, 2)}</pre>
          </>
        )}
        {device.last_resource_metrics && (
          <>
            <h3 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Last resource metrics</h3>
            <pre className="overflow-x-auto rounded-md bg-charcoal-900 p-3 text-xs text-slate-400">{JSON.stringify(device.last_resource_metrics, null, 2)}</pre>
          </>
        )}
      </Card>

      <Card className="md:col-span-2">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Lifecycle actions</h2>
        {canManage ? (
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setLifecycleAction('active')} disabled={!allowed.has('active')}>
              Activate
            </Button>
            <Button variant="danger" onClick={() => setLifecycleAction('suspended')} disabled={!allowed.has('suspended')}>
              Suspend
            </Button>
            <Button variant="danger" onClick={() => setLifecycleAction('maintenance')} disabled={!allowed.has('maintenance')}>
              Maintenance
            </Button>
            <Button variant="danger" onClick={() => setLifecycleAction('decommissioned')} disabled={!allowed.has('decommissioned')}>
              Decommission
            </Button>
            <Button variant="danger" onClick={() => setLifecycleAction('revoked')} disabled={!allowed.has('revoked')}>
              Revoke
            </Button>
            <Button variant="secondary" onClick={() => setShowRotate(true)} disabled={device.administrative_status === 'revoked'}>
              Rotate API key
            </Button>
          </div>
        ) : (
          <p className="text-xs text-slate-500">Administrator or analyst role required to manage device lifecycle.</p>
        )}
      </Card>

      {lifecycleAction && (
        <LifecyclePreviewDialog deviceId={device.id} target={lifecycleAction} onClose={() => setLifecycleAction(null)} onDone={onChanged} />
      )}
      {showRotate && <RotateKeyDialog deviceId={device.id} onClose={() => setShowRotate(false)} />}
      {showAssignSite && (
        <AssignSiteDialog
          deviceId={device.id}
          sites={sites}
          currentSiteId={device.site_id}
          onClose={() => setShowAssignSite(false)}
          onDone={onChanged}
        />
      )}
    </div>
  )
}

function CapabilitiesTab({ deviceId }: { deviceId: string }) {
  const [capabilities, setCapabilities] = useState<DeviceCapability[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.devices
      .capabilities(deviceId)
      .then((c) => {
        setCapabilities(c)
        setError(null)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load device capabilities.'))
  }, [deviceId])

  if (error) return <ErrorState message={error} />
  if (!capabilities) return <Spinner />
  if (capabilities.length === 0) return <EmptyState message="No capability records reported for this device yet." />

  return (
    <DataTable
      rows={capabilities.map((c, i) => ({ id: `${c.capability_key}-${i}`, ...c }))}
      columns={[
        { header: 'Capability', render: (c) => <span className="font-mono text-xs">{c.capability_key}</span> },
        { header: 'Supported', render: (c) => <BoolBadge value={c.supported} /> },
        { header: 'Installed', render: (c) => <BoolBadge value={c.installed} /> },
        { header: 'Available & ready', render: (c) => <BoolBadge value={c.available_and_ready} /> },
        { header: 'Healthy', render: (c) => <HealthyBadge value={c.healthy} /> },
        { header: 'Last verified', render: (c) => formatDateTime(c.last_verified_at) },
        { header: 'Last reported', render: (c) => formatDateTime(c.last_reported_at) },
      ]}
    />
  )
}

function NewBaselineDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (b: DeviceConfigBaseline) => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [version, setVersion] = useState('1')
  const [expectedConfigText, setExpectedConfigText] = useState('{}')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit() {
    setSubmitting(true)
    setError(null)
    try {
      let expectedConfig: Record<string, unknown>
      try {
        expectedConfig = JSON.parse(expectedConfigText)
      } catch {
        throw new Error('Expected config must be valid JSON.')
      }
      const versionNum = Number(version)
      if (!Number.isFinite(versionNum)) throw new Error('Version must be a number.')
      const baseline = await api.fleetConfig.createBaseline({
        name,
        description: description || undefined,
        version: versionNum,
        expected_config: expectedConfig,
      })
      onCreated(baseline)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Failed to create baseline.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal title="New configuration baseline" onClose={onClose}>
      <div className="grid gap-3">
        <Field label="Name">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        </Field>
        <Field label="Description (optional)">
          <input className={inputClass} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} />
        </Field>
        <Field label="Version">
          <input className={inputClass} value={version} onChange={(e) => setVersion(e.target.value)} />
        </Field>
        <Field label="Expected config (JSON)">
          <textarea className={`${inputClass} h-32 font-mono text-xs`} value={expectedConfigText} onChange={(e) => setExpectedConfigText(e.target.value)} />
        </Field>
      </div>
      {error && <div className="mt-3"><ErrorState message={error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={handleSubmit} disabled={submitting || !name.trim()}>
          {submitting ? 'Creating…' : 'Create baseline'}
        </Button>
      </div>
    </Modal>
  )
}

function ConfigurationTab({ deviceId, canManage }: { deviceId: string; canManage: boolean }) {
  const [configState, setConfigState] = useState<DeviceConfigState | null>(null)
  const [configText, setConfigText] = useState('')
  const [error, setError] = useState<string | null>(null)

  const [baselines, setBaselines] = useState<DeviceConfigBaseline[] | null>(null)
  const [selectedBaselineId, setSelectedBaselineId] = useState('')
  const [assigningBaseline, setAssigningBaseline] = useState(false)
  const [baselineError, setBaselineError] = useState<string | null>(null)
  const [showNewBaseline, setShowNewBaseline] = useState(false)

  const [configEditError, setConfigEditError] = useState<string | null>(null)
  const [savingConfig, setSavingConfig] = useState(false)

  function load() {
    api.devices
      .getConfig(deviceId)
      .then((c) => {
        setConfigState(c)
        setConfigText(JSON.stringify(c.current_config, null, 2))
        setError(null)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load device configuration.'))
  }

  useEffect(load, [deviceId])
  useEffect(() => {
    api.fleetConfig
      .listBaselines()
      .then(setBaselines)
      .catch(() => setBaselines([]))
  }, [])

  async function handleAssignBaseline() {
    if (!selectedBaselineId) return
    setAssigningBaseline(true)
    setBaselineError(null)
    try {
      const updated = await api.devices.assignBaseline(deviceId, selectedBaselineId)
      setConfigState(updated)
      setConfigText(JSON.stringify(updated.current_config, null, 2))
    } catch (err) {
      setBaselineError(err instanceof ApiError ? err.message : 'Failed to assign baseline.')
    } finally {
      setAssigningBaseline(false)
    }
  }

  async function handleSaveConfig() {
    if (!configState) return
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(configText)
    } catch {
      setConfigEditError('Not valid JSON.')
      return
    }
    setSavingConfig(true)
    setConfigEditError(null)
    try {
      const updated = await api.devices.updateConfig(deviceId, parsed, configState.config_revision)
      setConfigState(updated)
      setConfigText(JSON.stringify(updated.current_config, null, 2))
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setConfigEditError("Someone else changed this device's configuration since you loaded it -- this write was not applied. Reload this tab and try again.")
      } else {
        setConfigEditError(err instanceof ApiError ? err.message : 'Failed to save configuration.')
      }
    } finally {
      setSavingConfig(false)
    }
  }

  if (error) return <ErrorState message={error} />
  if (!configState) return <Spinner />

  const baselineName = configState.config_baseline_id
    ? baselines?.find((b) => b.id === configState.config_baseline_id)?.name ?? configState.config_baseline_id
    : null

  return (
    <div className="grid gap-4">
      <Card>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Configuration state</h2>
        <Row label="Config revision" value={configState.config_revision} />
        <Row label="Assigned baseline" value={baselineName ?? 'None assigned'} />
      </Card>

      <Card>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Configuration drift</h2>
        {!configState.drift.evaluated ? (
          <p className="text-sm text-slate-400">Not evaluated -- no baseline is currently assigned to this device (or the assigned baseline was deleted).</p>
        ) : configState.drift.has_drift === false ? (
          <p className="text-sm text-status-good">
            No drift detected{configState.drift.baseline_version != null ? ` against baseline v${configState.drift.baseline_version}` : ' against the assigned baseline'}.
          </p>
        ) : (
          <>
            <p className="mb-2 text-sm text-status-warning">
              {configState.drift.differences.length} difference{configState.drift.differences.length === 1 ? '' : 's'} found against the assigned baseline.
            </p>
            <DataTable
              rows={configState.drift.differences.map((d, i) => ({ id: `${d.key}-${i}`, ...d }))}
              columns={[
                { header: 'Key', render: (d) => <span className="font-mono text-xs">{d.key}</span> },
                { header: 'Current value', render: (d) => <span className="font-mono text-xs">{JSON.stringify(d.current_value)}</span> },
                { header: 'Expected value', render: (d) => <span className="font-mono text-xs">{JSON.stringify(d.expected_value)}</span> },
              ]}
            />
          </>
        )}
      </Card>

      {canManage && (
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Assign a baseline</h2>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Baseline">
              <select className={inputClass} value={selectedBaselineId} onChange={(e) => setSelectedBaselineId(e.target.value)}>
                <option value="">Select a baseline…</option>
                {(baselines ?? []).map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name} (v{b.version})
                  </option>
                ))}
              </select>
            </Field>
            <Button onClick={handleAssignBaseline} disabled={!selectedBaselineId || assigningBaseline}>
              {assigningBaseline ? 'Assigning…' : 'Assign baseline'}
            </Button>
            <Button variant="secondary" onClick={() => setShowNewBaseline(true)}>
              New baseline
            </Button>
          </div>
          {baselineError && <div className="mt-2"><ErrorState message={baselineError} /></div>}
        </Card>
      )}

      <Card>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Current config (revision {configState.config_revision})</h2>
        {canManage ? (
          <>
            <textarea className={`${inputClass} h-64 font-mono text-xs`} value={configText} onChange={(e) => setConfigText(e.target.value)} />
            {configEditError && <div className="mt-2"><ErrorState message={configEditError} /></div>}
            <div className="mt-2 flex justify-end">
              <Button onClick={handleSaveConfig} disabled={savingConfig}>
                {savingConfig ? 'Saving…' : 'Save configuration'}
              </Button>
            </div>
          </>
        ) : (
          <pre className="max-h-96 overflow-auto rounded-md bg-charcoal-900 p-3 text-xs text-slate-300">
            {JSON.stringify(configState.current_config, null, 2)}
          </pre>
        )}
      </Card>

      {showNewBaseline && (
        <NewBaselineDialog
          onClose={() => setShowNewBaseline(false)}
          onCreated={(b) => {
            setBaselines((prev) => [...(prev ?? []), b])
            setSelectedBaselineId(b.id)
          }}
        />
      )}
    </div>
  )
}

function SyncActivityTab({ deviceId }: { deviceId: string }) {
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<SyncRecord> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.edgeSync
      .records({ device_id: deviceId, page, page_size: 20 })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load sync activity.'))
  }, [deviceId, page])

  if (error) return <ErrorState message={error} />
  if (!data) return <Spinner />
  if (data.items.length === 0) return <EmptyState message="No sync records for this device." />

  return (
    <>
      <DataTable
        rows={data.items}
        columns={[
          { header: 'Record type', render: (r) => r.record_type },
          { header: 'Client record ID', render: (r) => <span className="font-mono text-xs">{r.client_record_id.slice(0, 12)}</span> },
          { header: 'Status', render: (r) => <StatusPill status={r.sync_status} /> },
          { header: 'Retries', render: (r) => r.retry_count },
          { header: 'Queued', render: (r) => formatDateTime(r.queued_at) },
          { header: 'Processed', render: (r) => formatDateTime(r.processed_at) },
          { header: 'Last error', render: (r) => r.last_error_message ?? '--' },
        ]}
      />
      <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
    </>
  )
}

function HealthHistoryTab({ deviceId }: { deviceId: string }) {
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<DeviceHealthReport> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.devices
      .healthReports(deviceId, page, 20)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load health history.'))
  }, [deviceId, page])

  if (error) return <ErrorState message={error} />
  if (!data) return <Spinner />
  if (data.items.length === 0) return <EmptyState message="No health reports from this device yet." />

  return (
    <>
      <DataTable
        rows={data.items}
        columns={[
          { header: 'Reported', render: (r) => formatDateTime(r.reported_at) },
          { header: 'Connectivity', render: (r) => <StatusPill status={r.connectivity_state} /> },
          { header: 'Queue depth', render: (r) => r.queue_depth ?? '--' },
          { header: 'Pending sync', render: (r) => r.pending_sync_count ?? '--' },
          { header: 'Software version', render: (r) => r.software_version ?? '--' },
          { header: 'Runtime capabilities', render: (r) => (r.runtime_capabilities?.length ? r.runtime_capabilities.join(', ') : '--') },
        ]}
      />
      <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
    </>
  )
}

function AuditTrailTab({ deviceId }: { deviceId: string }) {
  const [records, setRecords] = useState<AuditRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.devices
      .statusHistory(deviceId)
      .then((d) => {
        setRecords(d)
        setError(null)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load audit trail.'))
  }, [deviceId])

  if (error) return <ErrorState message={error} />
  if (!records) return <Spinner />
  if (records.length === 0) return <EmptyState message="No audit history for this device." />

  return (
    <ul className="space-y-2 text-xs">
      {records.map((r) => (
        <li key={r.id} className="flex items-center justify-between border-b border-charcoal-700/50 pb-2 last:border-0">
          <span className="text-slate-300">{r.action}</span>
          <StatusPill status={r.outcome} />
          <span className="text-slate-500">{formatDateTime(r.created_at)}</span>
        </li>
      ))}
    </ul>
  )
}

export function EdgeDeviceDetailPage() {
  const { deviceId } = useParams<{ deviceId: string }>()
  const { user } = useAuth()
  const [device, setDevice] = useState<Device | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabKey>('overview')
  const [sites, setSites] = useState<FleetSite[]>([])

  const canManage = user?.role === 'administrator' || user?.role === 'analyst'

  useEffect(() => {
    if (!deviceId) return
    api.devices
      .get(deviceId)
      .then(setDevice)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load device.'))
  }, [deviceId])

  useEffect(() => {
    api.fleetSites
      .list()
      .then(setSites)
      .catch(() => setSites([]))
  }, [])

  if (error) return <ErrorState message={error} />
  if (!device) return <Spinner />

  return (
    <div>
      <PageHeader
        title={device.device_name}
        description={
          <>
            <Link to="/edge/devices" className="text-accent-400 hover:underline">
              Edge Devices
            </Link>{' '}
            / <span className="font-mono">{device.device_identifier}</span>
          </>
        }
      />

      <Tabs
        active={tab}
        onChange={(k) => setTab(k as TabKey)}
        tabs={[
          { key: 'overview', label: 'Overview' },
          { key: 'capabilities', label: 'Capabilities' },
          { key: 'config', label: 'Configuration' },
          { key: 'sync', label: 'Sync Activity' },
          { key: 'health', label: 'Health History' },
          { key: 'audit', label: 'Audit Trail' },
        ]}
      />

      {tab === 'overview' && <OverviewTab device={device} canManage={canManage} sites={sites} onChanged={setDevice} />}
      {tab === 'capabilities' && <CapabilitiesTab deviceId={device.id} />}
      {tab === 'config' && <ConfigurationTab deviceId={device.id} canManage={canManage} />}
      {tab === 'sync' && <SyncActivityTab deviceId={device.id} />}
      {tab === 'health' && <HealthHistoryTab deviceId={device.id} />}
      {tab === 'audit' && <AuditTrailTab deviceId={device.id} />}
    </div>
  )
}
