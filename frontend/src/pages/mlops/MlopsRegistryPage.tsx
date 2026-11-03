import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mlopsApi } from '../../api/mlops'
import { useAuth } from '../../context/auth'
import type { LifecycleState, ModelFamily, ModelVersion, TaskType } from '../../types/mlops'
import type { Page } from '../../types/api'
import { DataTable } from '../../components/tables/DataTable'
import { Button, EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatusPill, Tabs, inputClass } from '../../components/ui/Primitives'
import { Notice } from '../../components/mlops/shared'
import { canReview, fmtDate } from '../../components/mlops/format'

const STATES: LifecycleState[] = ['registered', 'review_required', 'approved', 'deprecated', 'archived']

/** Model registry: families (derived from version names) and immutable versions. */
export function MlopsRegistryPage() {
  const nav = useNavigate()
  const { user } = useAuth()
  const [tab, setTab] = useState('versions')
  const [q, setQ] = useState('')
  const [task, setTask] = useState('')
  const [state, setState] = useState('')
  const [family, setFamily] = useState('')
  const [page, setPage] = useState(1)
  const [versions, setVersions] = useState<Page<ModelVersion> | null>(null)
  const [families, setFamilies] = useState<Page<ModelFamily> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [showRegister, setShowRegister] = useState(false)

  const load = useCallback(() => {
    setLoading(true); setError(null)
    const p = tab === 'versions'
      ? mlopsApi.versions({ q, task, lifecycle_state: state, family }, page).then(setVersions)
      : mlopsApi.families(q).then(setFamilies)
    p.catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [tab, q, task, state, family, page])
  useEffect(load, [load])

  return (
    <div>
      <PageHeader
        title="Model Registry"
        description="Registered model versions are immutable: to change a model, register a new version. Approval is registry metadata only — AEGIS has no serving environment, so nothing is deployed by approving a version."
        actions={canReview(user?.role) ? <Button onClick={() => setShowRegister(true)}>Register version</Button> : undefined}
      />
      <Tabs tabs={[{ key: 'versions', label: 'Versions' }, { key: 'families', label: 'Families' }]} active={tab} onChange={(k) => { setTab(k); setPage(1) }} />
      <div className="mb-4 grid gap-3 md:grid-cols-4">
        <Field label="Search name or version"><input className={inputClass} value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} maxLength={100} /></Field>
        {tab === 'versions' && (
          <>
            <Field label="Task">
              <select className={inputClass} value={task} onChange={(e) => { setTask(e.target.value); setPage(1) }}>
                <option value="">All</option><option value="object_detection">object_detection</option><option value="classification">classification</option>
              </select>
            </Field>
            <Field label="Lifecycle state">
              <select className={inputClass} value={state} onChange={(e) => { setState(e.target.value); setPage(1) }}>
                <option value="">All</option>{STATES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
              </select>
            </Field>
            <Field label="Family"><input className={inputClass} value={family} onChange={(e) => { setFamily(e.target.value); setPage(1) }} maxLength={100} /></Field>
          </>
        )}
      </div>
      {error && <ErrorState message={error} />}
      {loading && <Spinner />}
      {!loading && !error && tab === 'versions' && versions && (
        versions.items.length === 0 ? <EmptyState message="No model versions match these filters." /> : (
          <>
            <DataTable
              rows={versions.items}
              onRowClick={(m) => nav(`/mlops/models/${m.id}`)}
              columns={[
                { header: 'Model', render: (m) => <div><div className="text-slate-100">{m.name} <span className="text-slate-400">{m.version}</span></div><div className="text-xs text-slate-500">{m.scope === 'platform' ? 'platform-level (shared)' : m.owned_by_your_organization ? 'your organization' : 'organization'}</div></div> },
                { header: 'Task', render: (m) => m.task_type ?? 'unspecified' },
                { header: 'Lifecycle', render: (m) => <StatusPill status={m.lifecycle_state} /> },
                { header: 'Latest evaluation', render: (m) => <div><StatusPill status={m.evaluation.status} /><div className="text-xs text-slate-500">{m.evaluation.run_count} run(s){m.evaluation.latest_succeeded_at ? ` · last success ${fmtDate(m.evaluation.latest_succeeded_at)}` : ''}</div></div> },
                { header: 'Artifact', render: (m) => <span className={m.artifact.available ? 'text-status-good' : 'text-status-warning'} title={m.artifact.reason ?? ''}>{m.artifact.available ? 'available' : 'unavailable'}</span> },
                { header: 'Registered', render: (m) => fmtDate(m.created_at) },
              ]}
            />
            <Pager page={versions.page} size={versions.page_size} total={versions.total} onPage={setPage} />
          </>
        )
      )}
      {!loading && !error && tab === 'families' && families && (
        families.items.length === 0 ? <EmptyState message="No model families yet. A family is the set of versions sharing a name." /> : (
          <DataTable
            rows={families.items.map((f) => ({ ...f, id: f.name }))}
            onRowClick={(f) => { setFamily(f.name); setTab('versions'); setPage(1) }}
            columns={[
              { header: 'Family', render: (f) => <span className="text-slate-100">{f.name}</span> },
              { header: 'Versions', render: (f) => f.version_count },
              { header: 'Latest', render: (f) => f.latest_version ?? '—' },
              { header: 'Tasks', render: (f) => f.task_types.join(', ') || 'unspecified' },
              { header: 'States', render: (f) => Object.entries(f.lifecycle_counts).map(([k, v]) => `${k.replace('_', ' ')}: ${v}`).join(' · ') },
            ]}
          />
        )
      )}
      {showRegister && <RegisterModal onClose={() => setShowRegister(false)} onDone={(id) => nav(`/mlops/models/${id}`)} />}
    </div>
  )
}

function Pager({ page, size, total, onPage }: { page: number; size: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size))
  return (
    <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
      <span>{total} total · page {page} of {pages}</span>
      <div className="flex gap-2"><Button variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button><Button variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button></div>
    </div>
  )
}

function RegisterModal({ onClose, onDone }: { onClose: () => void; onDone: (id: string) => void }) {
  const [name, setName] = useState('')
  const [version, setVersion] = useState('')
  const [task, setTask] = useState<TaskType>('classification')
  const [adapter, setAdapter] = useState('mock_detector_v1')
  const [artifact, setArtifact] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const submit = async () => {
    setBusy(true); setError(null)
    try {
      const body: Record<string, unknown> = { name, version, task_type: task }
      if (task === 'object_detection') { body.adapter_key = adapter; body.supported_media_types = ['image'] }
      if (artifact.trim()) body.artifact_reference = artifact.trim()
      if (notes.trim()) body.release_notes = notes.trim()
      const created = await mlopsApi.registerVersion(body)
      onDone(created.id)
    } catch (e) { setError((e as Error).message); setBusy(false) }
  }
  return (
    <Modal title="Register model version" onClose={onClose}>
      <Notice>Versions are immutable after registration. The server validates the name, semantic version, adapter and artifact reference (relative paths under the configured artifact root only; no URLs).</Notice>
      <div className="space-y-3">
        <Field label="Name"><input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
        <Field label="Version (semantic, e.g. 1.0.0)"><input className={inputClass} value={version} onChange={(e) => setVersion(e.target.value)} maxLength={40} /></Field>
        <Field label="Task">
          <select className={inputClass} value={task} onChange={(e) => setTask(e.target.value as TaskType)}><option value="classification">classification</option><option value="object_detection">object_detection</option></select>
        </Field>
        {task === 'object_detection' && (
          <Field label="Detector adapter">
            <select className={inputClass} value={adapter} onChange={(e) => setAdapter(e.target.value)}><option value="mock_detector_v1">mock_detector_v1</option><option value="opencv_hog_person_v1">opencv_hog_person_v1</option></select>
          </Field>
        )}
        <Field label="Artifact reference (optional, artifact:relative/path)"><input className={inputClass} value={artifact} onChange={(e) => setArtifact(e.target.value)} maxLength={300} /></Field>
        <Field label="Release notes (optional)"><textarea className={inputClass} rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={4000} /></Field>
        {error && <ErrorState message={error} />}
        <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy || !name || !version}>Register</Button></div>
      </div>
    </Modal>
  )
}
export { Pager }
