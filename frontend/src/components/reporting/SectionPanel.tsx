import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { AnalyticsTable, SectionEnvelope } from '../../types/reporting'
import { Card } from '../ui/Primitives'
import { BarSeries, HBars } from './Charts'
import { useMetricCatalog } from './catalog'
import { fmtMetric, fmtTime, fmtWindow, humanize } from './format'

/** Context line shown on every section: window, time basis, generation time, freshness and sample counts. */
export function ContextLine({ env }: { env: SectionEnvelope }) {
  const fr = env.freshness
  const counts = Object.entries(env.sample_counts).map(([k, v]) => `${v.toLocaleString()} ${humanize(k)}`).join(' · ')
  return (
    <div className="mb-2 space-y-1 text-xs text-slate-500">
      <p>Window {fmtWindow(env.window)} · {env.window.time_basis} time · {env.window.bucket} buckets · generated {fmtTime(env.generated_at)} · definitions v{env.definition_version}</p>
      <p>{counts || 'No sample counts available'}{fr?.age_hours != null ? ` · newest record ${fr.age_hours} h old` : ''}</p>
      {fr?.stale && <p role="status" className="text-status-warning">Stale: the newest record is older than {fr.stale_after_hours} hours, so recent windows may be incomplete.</p>}
    </div>
  )
}

export function StateBanner({ env }: { env: SectionEnvelope }) {
  if (env.status === 'not_authorized') return <p role="status" className="rounded-md border border-charcoal-600 bg-charcoal-800/60 px-3 py-2 text-sm text-slate-400">You do not have permission to see this section. No figures from it are shown.</p>
  if (env.status === 'empty') return <p role="status" className="rounded-md border border-dashed border-charcoal-600 px-3 py-2 text-sm text-slate-400">No stored records match this window and these filters. That does not show that nothing happened — only that nothing is recorded.</p>
  if (env.status === 'partial') return <p role="status" className="rounded-md border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-sm text-status-warning">Partial data — some figures are omitted or truncated; see the notes below.</p>
  return null
}

function isSeries(t: AnalyticsTable, id: string) { return id.includes('by_bucket') && t.columns.length >= 2 && typeof t.rows[0]?.[1] === 'number' }

function TableView({ id, t, env, onPick }: { id: string; t: AnalyticsTable; env: SectionEnvelope; onPick?: (metricId: string, v: string) => void }) {
  const wt = fmtWindow(env.window)
  const metric = t.metric_ids[0]
  const numeric = t.columns.length === 2 && t.rows.every((r) => typeof r[1] === 'number')
  const pickable = onPick && env.drilldown[metric]?.includes('{value}')
  return (
    <div className="mt-4">
      <h5 className="mb-1 text-sm font-semibold text-slate-100">{t.title}</h5>
      {isSeries(t, id) ? (
        <BarSeries title={t.title} unit={t.unit} windowText={wt} rows={t.rows.map((r) => [String(r[0]), t.columns.slice(1).reduce((a, _c, i) => a + Number(r[i + 1] ?? 0), 0)])} />
      ) : numeric && t.rows.length > 0 ? (
        <HBars title={t.title} unit={t.unit} windowText={wt} rows={t.rows.map((r) => [String(r[0]), r[1] as number])} onPick={pickable ? (label) => onPick!(metric, label) : undefined} />
      ) : null}
      <details className="mt-1">
        <summary className="cursor-pointer text-xs text-slate-500">View as table ({t.rows.length} rows · unit: {t.unit})</summary>
        <div className="mt-1 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <caption className="sr-only">{t.title}</caption>
            <thead><tr className="text-slate-500">{t.columns.map((c) => <th key={c} scope="col" className="px-2 py-1 font-medium">{humanize(c)}</th>)}</tr></thead>
            <tbody>
              {t.rows.length === 0 && <tr><td colSpan={t.columns.length} className="px-2 py-2 text-slate-500">No rows.</td></tr>}
              {t.rows.map((r, i) => <tr key={i} className="border-t border-charcoal-700/60">{r.map((c, j) => <td key={j} className="px-2 py-1 tabular-nums text-slate-300">{c === null ? <span className="text-slate-500">n/a</span> : String(c)}</td>)}</tr>)}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}

/** Renders any analytics section generically so every dashboard shows the same definitions, states and caveats. */
export function SectionPanel({ env, title, onPick, hideTables = [] }: { env: SectionEnvelope; title: string; onPick?: (metricId: string, v: string) => void; hideTables?: string[] }) {
  const defs = useMetricCatalog()
  const [showNotes, setShowNotes] = useState(false)
  const links = [...new Set(Object.values(env.drilldown).filter((p) => !p.includes('{')))]
  return (
    <Card>
      <h4 className="mb-1 text-base font-semibold text-slate-100">{title}</h4>
      <ContextLine env={env} />
      <StateBanner env={env} />
      {env.status !== 'not_authorized' && (
        <>
          <dl className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(env.values).map(([id, v]) => (
              <div key={id} className="rounded-md border border-charcoal-700 bg-charcoal-900/50 px-3 py-2">
                <dt className="text-xs text-slate-400"><abbr title={defs[id]?.definition ?? id} className="cursor-help no-underline decoration-dotted underline-offset-2 hover:underline">{defs[id]?.label ?? humanize(id)}</abbr></dt>
                <dd className={`text-lg tabular-nums ${v.value === null ? 'text-slate-500' : 'text-slate-100'}`}>{fmtMetric(v)}</dd>
                {v.n !== null && <div className="text-[11px] text-slate-500">n = {v.n.toLocaleString()}</div>}
              </div>
            ))}
          </dl>
          {Object.entries(env.tables).filter(([id]) => !hideTables.includes(id)).map(([id, t]) => <TableView key={id} id={id} t={t} env={env} onPick={onPick} />)}
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
            {links.map((p) => <Link key={p} to={p} className="text-accent-400 hover:underline">Open {p}</Link>)}
            {env.caveats.length > 0 && <button type="button" className="text-slate-400 underline" aria-expanded={showNotes} onClick={() => setShowNotes(!showNotes)}>{showNotes ? 'Hide' : 'Show'} notes & limitations ({env.caveats.length})</button>}
          </div>
          {showNotes && <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-400">{env.caveats.map((c) => <li key={c}>{c}</li>)}</ul>}
        </>
      )}
    </Card>
  )
}
