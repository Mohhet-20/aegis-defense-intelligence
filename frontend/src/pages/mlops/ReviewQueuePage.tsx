import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { mlopsApi } from '../../api/mlops'
import { useAuth } from '../../context/auth'
import type { ReviewSignal, SignalPage } from '../../types/mlops'
import { DataTable } from '../../components/tables/DataTable'
import { Button, EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatTile, StatusPill, inputClass } from '../../components/ui/Primitives'
import { Notice } from '../../components/mlops/shared'
import { canReview, fmtDate } from '../../components/mlops/format'
import { Pager } from './MlopsRegistryPage'

/** Review queue: deduplicated signals that crossed a configured threshold. Signals are prompts to look, not findings. */
export function ReviewQueuePage() {
  const { user } = useAuth()
  const [data, setData] = useState<SignalPage | null>(null)
  const [status, setStatus] = useState('open')
  const [severity, setSeverity] = useState('')
  const [category, setCategory] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<ReviewSignal | null>(null)
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    setLoading(true); setError(null)
    mlopsApi.signals({ status, severity, category }, page).then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [status, severity, category, page])
  useEffect(load, [load])

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setError(null)
    try { await fn(); setNotice(ok); setSelected(null); setNotes(''); load() } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const unresolved = data?.counts.unresolved_by_severity ?? {}

  return (
    <div>
      <PageHeader title="Review Queue" description="A review signal means a measured value crossed a configured threshold. It is not evidence of a real-world condition and triggers no automatic action. Repeated observations are merged into one signal." 
        actions={canReview(user?.role) ? <Button variant="secondary" disabled={busy} onClick={() => act(() => mlopsApi.scan(), 'Scan complete (stale runs, evaluation staleness and job failure rates checked).')}>Run checks now</Button> : undefined} />
      {notice && <div className="mb-3 rounded-md border border-status-good/40 bg-status-good/10 px-3 py-2 text-sm text-status-good">{notice}</div>}
      <div className="mb-4 grid gap-3 md:grid-cols-4">
        {(['critical', 'serious', 'warning', 'info'] as const).map((s) => <StatTile key={s} label={`Unresolved ${s}`} value={unresolved[s] ?? 0} />)}
      </div>
      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <Field label="Status"><select className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}><option value="">All</option><option value="open">open</option><option value="acknowledged">acknowledged</option><option value="resolved">resolved</option></select></Field>
        <Field label="Severity"><select className={inputClass} value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1) }}><option value="">All</option>{['critical', 'serious', 'warning', 'info'].map((s) => <option key={s} value={s}>{s}</option>)}</select></Field>
        <Field label="Category (exact)"><input className={inputClass} value={category} maxLength={40} onChange={(e) => { setCategory(e.target.value); setPage(1) }} placeholder="e.g. data_drift" /></Field>
      </div>
      {error && <ErrorState message={error} />}
      {loading && <Spinner />}
      {!loading && !error && data && (data.items.length === 0 ? <EmptyState message="No review signals match. An empty queue means no configured threshold has been crossed in the checks that have run — not that everything is verified." /> : (
        <>
          <DataTable rows={data.items} onRowClick={setSelected} columns={[
            { header: 'Severity', render: (s) => <StatusPill status={s.severity} /> },
            { header: 'Signal', render: (s) => <div><div className="text-slate-100">{s.title}</div><div className="text-xs text-slate-500">{s.category.replace(/_/g, ' ')}</div></div> },
            { header: 'Status', render: (s) => <StatusPill status={s.status} /> },
            { header: 'Seen', render: (s) => `${s.occurrence_count}× · last ${fmtDate(s.last_seen_at)}` },
          ]} />
          <Pager page={data.page} size={data.page_size} total={data.total} onPage={setPage} />
        </>
      ))}
      {selected && (
        <Modal title={selected.title} onClose={() => setSelected(null)}>
          <div className="space-y-3 text-sm">
            <Notice>{selected.advisory_notice}</Notice>
            <p className="text-slate-300">{selected.summary}</p>
            <dl className="space-y-1 text-xs text-slate-400">
              {selected.observed_value != null && <div>Observed: {selected.observed_value} · Threshold: {selected.threshold_value ?? '—'}</div>}
              {selected.model_record_id && <div>Model: <Link className="text-accent-400" to={`/mlops/models/${selected.model_record_id}`}>{selected.model_name} {selected.model_version}</Link></div>}
              <div>First seen {fmtDate(selected.first_seen_at)} · last seen {fmtDate(selected.last_seen_at)} · {selected.occurrence_count} occurrence(s)</div>
              {selected.limitations && <div>Limitations: {selected.limitations}</div>}
              {selected.resolution_notes && <div>Resolution: {selected.resolution_notes}</div>}
            </dl>
            <details className="text-xs text-slate-500"><summary className="cursor-pointer">Evidence (bounded JSON)</summary><pre className="mt-1 max-h-48 overflow-auto rounded-sm bg-charcoal-900 p-2">{JSON.stringify(selected.evidence, null, 2)}</pre></details>
            {canReview(user?.role) && selected.status !== 'resolved' && (
              <div className="space-y-2">
                {selected.status === 'open' && <Button variant="secondary" disabled={busy} onClick={() => act(() => mlopsApi.acknowledge(selected.id), 'Signal acknowledged.')}>Acknowledge</Button>}
                <Field label="Resolution notes (required, min 3 characters)"><textarea className={inputClass} rows={3} value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} /></Field>
                <Button disabled={busy || notes.trim().length < 3} onClick={() => act(() => mlopsApi.resolve(selected.id, notes.trim()), 'Signal resolved.')}>Resolve</Button>
                <p className="text-xs text-slate-500">Resolving is manual and audited. Nothing resolves automatically when a metric recovers.</p>
              </div>
            )}
          </div>
        </Modal>
      )}
    </div>
  )
}
