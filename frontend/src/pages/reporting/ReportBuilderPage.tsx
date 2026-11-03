import { useCallback, useEffect, useState } from 'react'
import { reportingApi } from '../../api/reporting'
import type { ReportBody, ReportRunInfo, ReportTemplate, TemplateList } from '../../types/reporting'
import { FilterBar } from '../../components/reporting/FilterBar'
import { useReportingFilters } from '../../components/reporting/useFilters'
import { fmtTime, humanize } from '../../components/reporting/format'
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, inputClass } from '../../components/ui/Primitives'

const ALL_SECTIONS = ['events', 'observations', 'ingestion', 'fusion', 'sensors', 'investigations', 'evidence', 'models', 'system', 'geo', 'review_backlog']
const STATUS_TONE: Record<string, string> = { completed: 'text-status-good', failed: 'text-status-critical', running: 'text-accent-400', expired: 'text-slate-500' }

function RunRow({ run, onDownload, busy }: { run: ReportRunInfo; onDownload: (r: ReportRunInfo) => void; busy: boolean }) {
  return (
    <li className="rounded-md border border-charcoal-700 bg-charcoal-900/40 p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="font-medium text-slate-100">{run.title}</span>
          <span className={`ml-2 text-xs font-semibold uppercase ${STATUS_TONE[run.status] ?? 'text-slate-300'}`}>{run.status}</span>
        </div>
        {run.downloadable
          ? <Button variant="secondary" disabled={busy} onClick={() => onDownload(run)}>Download {run.format.toUpperCase()}</Button>
          : <span className="text-xs text-slate-500">{run.status === 'expired' ? 'File deleted after retention period' : run.status === 'failed' ? 'No file was produced' : 'Not available'}</span>}
      </div>
      <p className="mt-1 text-xs text-slate-500">
        {humanize(run.template_key)} · {run.format} · {run.visibility} · created {fmtTime(run.created_at)}
        {run.expires_at && run.status === 'completed' ? ` · file kept until ${fmtTime(run.expires_at)}` : ''}
        {run.artifact_bytes != null ? ` · ${run.artifact_bytes.toLocaleString()} bytes` : ''} · downloaded {run.download_count}×
      </p>
      {run.status === 'failed' && <p role="alert" className="mt-1 text-xs text-status-critical">Failed ({run.error_category}): {run.error_message}</p>}
      {Object.keys(run.sample_summary).length > 0 && <p className="mt-1 text-xs text-slate-400">Included: {Object.entries(run.section_status).map(([k, v]) => `${humanize(k)} (${v}${run.sample_summary[k] ? `, ${Object.entries(run.sample_summary[k]).map(([a, b]) => `${b} ${humanize(a)}`).join('/')}` : ''})`).join(' · ')}</p>}
      {run.content_sha256 && <p className="mt-1 break-all text-[11px] text-slate-600" title={run.integrity_note}>SHA-256 (integrity check of the stored file only): {run.content_sha256}</p>}
    </li>
  )
}

export function ReportBuilderPage() {
  const [filters, setFilters] = useReportingFilters()
  const [tpl, setTpl] = useState<TemplateList | null>(null)
  const [runs, setRuns] = useState<ReportRunInfo[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [key, setKey] = useState('platform_activity')
  const [format, setFormat] = useState('json')
  const [title, setTitle] = useState('')
  const [notes, setNotes] = useState('')
  const [visibility, setVisibility] = useState('private')
  const [sections, setSections] = useState<string[]>(['events'])
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(() => reportingApi.list(1).then((p) => setRuns(p.items)).catch((e) => setError(e.message)), [])
  useEffect(() => { reportingApi.templates().then(setTpl).catch((e) => setError(e.message)); refresh() }, [refresh])

  const selected: ReportTemplate | undefined = tpl?.templates.find((t) => t.key === key)
  const body = (): ReportBody => ({
    template_key: key, title: title.trim() || undefined, format, sections: selected?.custom_sections ? sections : undefined,
    days: filters.start && filters.end ? undefined : filters.days, start: filters.start, end: filters.end, bucket: filters.bucket, time_basis: filters.time_basis,
    source_id: filters.source_id || undefined, category: filters.category || undefined, include_archived: filters.include_archived, notes: notes.trim() || undefined, visibility,
    idempotency_key: undefined,
  })
  const run = async (kind: 'validate' | 'create') => {
    setBusy(true); setMessage(null); setError(null)
    try {
      if (kind === 'validate') {
        const v = await reportingApi.validate(body()) as { sections: string[]; required_permissions: string[]; window: { start: string; end: string } }
        setMessage(`Valid. Sections: ${v.sections.map(humanize).join(', ')}. Window ${v.window.start} → ${v.window.end} (UTC, end exclusive). Needs: ${v.required_permissions.join(', ') || 'none beyond report generation'}.`)
      } else {
        const r = await reportingApi.create({ ...body(), idempotency_key: crypto.randomUUID() })
        setMessage(r.status === 'completed' ? `Report ready: ${r.title}.` : `The report did not complete (${r.status}): ${r.error_message ?? 'see history'}`)
        await refresh()
      }
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const download = async (r: ReportRunInfo) => { setBusy(true); setError(null); try { await reportingApi.download(r); await refresh() } catch (e) { setError((e as Error).message); await refresh() } finally { setBusy(false) } }

  return (
    <div>
      <PageHeader title="Reports" description="Generate a report from the same definitions the dashboards use. Automatic findings, your commentary and any model-written text are kept separate in every file. PDF is not supported." />
      {error && <ErrorState message={error} />}
      {!tpl && !error && <Spinner />}
      {tpl && (
        <Card>
          <form onSubmit={(e) => { e.preventDefault(); void run('create') }} aria-label="Report builder">
            <div className="grid gap-3 md:grid-cols-3">
              <Field label="Template">
                <select className={inputClass} value={key} onChange={(e) => setKey(e.target.value)}>
                  {tpl.templates.map((t) => <option key={t.key} value={t.key} disabled={!t.available}>{t.title}{t.available ? '' : ' (not permitted)'}</option>)}
                </select>
              </Field>
              <Field label="Format">
                <select className={inputClass} value={format} onChange={(e) => setFormat(e.target.value)}>{tpl.formats.map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}</select>
              </Field>
              <Field label="Who can read it">
                <select className={inputClass} value={visibility} onChange={(e) => setVisibility(e.target.value)}>
                  <option value="private">Only me (and administrators)</option><option value="organization">My organization (with the needed permissions)</option>
                </select>
              </Field>
            </div>
            {selected && <p className="mt-2 text-xs text-slate-500">{selected.description} Sections: {selected.sections.map(humanize).join(', ')}.</p>}
            {selected?.custom_sections && (
              <fieldset className="mt-3 flex flex-wrap gap-3 text-sm text-slate-300"><legend className="mb-1 text-xs text-slate-400">Sections</legend>
                {ALL_SECTIONS.map((s) => <label key={s} className="flex items-center gap-1"><input type="checkbox" checked={sections.includes(s)} onChange={(e) => setSections(e.target.checked ? [...sections, s] : sections.filter((x) => x !== s))} />{humanize(s)}</label>)}
              </fieldset>
            )}
            <div className="mt-3"><FilterBar filters={filters} onChange={setFilters} /></div>
            <Field label="Title (optional)"><input className={inputClass} maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
            <div className="mt-3">
              <Field label={`Analyst commentary (optional, plain text, ${notes.length}/4000) — shown separately from automatic findings; AEGIS does not verify it`}>
                <textarea className={inputClass} rows={4} maxLength={4000} value={notes} onChange={(e) => setNotes(e.target.value)} />
              </Field>
            </div>
            <div className="mt-3 flex gap-2">
              <Button variant="secondary" disabled={busy} onClick={() => void run('validate')}>Check</Button>
              <Button type="submit" disabled={busy || !selected?.available || (selected?.custom_sections === true && sections.length === 0)}>Generate report</Button>
            </div>
            {message && <p role="status" className="mt-2 text-sm text-slate-300">{message}</p>}
          </form>
          <p className="mt-3 text-xs text-slate-500">Files are kept for {tpl.retention_days} days, are private to you and your administrators (or your organization if shared), and are only available through this page. The SHA-256 shown in history lets you check that a file is unchanged; it does not prove who made it.</p>
        </Card>
      )}
      <h4 className="mb-2 mt-6 text-sm font-semibold text-slate-100">History</h4>
      {runs === null ? <Spinner /> : runs.length === 0 ? <EmptyState message="No reports yet." /> : <ul className="space-y-2" aria-label="Report history">{runs.map((r) => <RunRow key={r.id} run={r} onDownload={download} busy={busy} />)}</ul>}
    </div>
  )
}
