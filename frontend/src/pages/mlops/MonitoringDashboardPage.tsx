import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { mlopsApi } from '../../api/mlops'
import type { Coverage, CoverageItem, DailyCount, DriftReport, ObservabilitySummary } from '../../types/mlops'
import { DataTable } from '../../components/tables/DataTable'
import { Card, EmptyState, ErrorState, PageHeader, Spinner, StatTile, StatusPill } from '../../components/ui/Primitives'
import { Notice } from '../../components/mlops/shared'
import { fmtDate, pct } from '../../components/mlops/format'

/** A stacked-by-total bar chart of daily counts. Caption states the quantity, window and unit. */
function DailyBars({ title, unit, days, rows, failedKey }: { title: string; unit: string; days: number; rows: DailyCount[]; failedKey: string }) {
  const max = Math.max(1, ...rows.map((r) => r.total))
  const total = rows.reduce((a, r) => a + r.total, 0)
  if (total === 0) return <div className="rounded-md border border-dashed border-charcoal-600 px-4 py-6 text-center text-xs text-slate-500">{title}: none recorded in the last {days} days.</div>
  const W = 560, H = 120, bw = (W - 20) / rows.length
  const caption = `${title}, last ${days} days · unit: ${unit} per UTC day`
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H + 18}`} role="img" aria-label={caption} className="w-full">
        {rows.map((r, i) => {
          const h = (r.total / max) * H, f = ((r.counts[failedKey] ?? 0) / max) * H
          return (
            <g key={r.date}>
              <rect x={10 + i * bw + 1} y={H - h} width={Math.max(1, bw - 2)} height={h} className="fill-accent-500/70"><title>{`${r.date}: ${r.total} (${r.counts[failedKey] ?? 0} ${failedKey})`}</title></rect>
              {f > 0 && <rect x={10 + i * bw + 1} y={H - f} width={Math.max(1, bw - 2)} height={f} className="fill-status-critical/80" />}
            </g>
          )
        })}
        <text x={10} y={H + 13} fontSize={10} className="fill-slate-500">{rows[0].date}</text>
        <text x={W - 10} y={H + 13} fontSize={10} textAnchor="end" className="fill-slate-500">{rows[rows.length - 1].date}</text>
        <text x={W - 10} y={10} fontSize={10} textAnchor="end" className="fill-slate-500">max {max}</text>
      </svg>
      <figcaption className="mt-1 text-xs text-slate-500">{caption}. Red = {failedKey}.</figcaption>
    </figure>
  )
}

const LEVEL_TONE: Record<string, string> = { no_material_change: 'text-status-good', moderate_shift: 'text-status-warning', large_shift: 'text-status-critical', not_assessable: 'text-slate-500' }

function Section({ title, status, reason, children }: { title: string; status: string; reason?: string | null; children?: React.ReactNode }) {
  return (
    <Card>
      <div className="flex items-center justify-between"><h4 className="text-sm font-semibold text-slate-100">{title}</h4><span className={`text-xs ${LEVEL_TONE[status] ?? 'text-slate-300'}`}>{status.replace(/_/g, ' ')}</span></div>
      {reason && <p className="mt-1 text-xs text-slate-500">{reason}</p>}
      {children}
    </Card>
  )
}

function DriftPanel({ item }: { item: CoverageItem }) {
  const [report, setReport] = useState<DriftReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!item.latest_current_snapshot_id) return
    mlopsApi.drift(item.latest_current_snapshot_id).then(setReport).catch((e) => setError(e.message))
  }, [item.latest_current_snapshot_id])
  if (error) return <ErrorState message={error} />
  if (!report) return <Spinner />
  const { data_drift: dd, prediction_drift: pd, performance: perf, operational: op } = report
  return (
    <div className="space-y-3">
      <Notice>{report.interpretation.join(' ')} Window {fmtDate(report.window.start)} – {fmtDate(report.window.end)} · {report.sample_counts.current} samples ({report.sample_counts.current_labelled} labelled) vs {report.sample_counts.reference ?? 'no'} reference samples. Thresholds: PSI warn {report.thresholds.psi_warn}, alert {report.thresholds.psi_alert}; minimum {report.thresholds.min_samples} samples.</Notice>
      <div className="grid gap-3 md:grid-cols-2">
        <Section title="Input (data) drift" status={dd.status} reason={dd.reason}>
          {dd.features.length > 0 && <ul className="mt-2 space-y-0.5 text-xs text-slate-300">{dd.features.map((f) => <li key={f.feature}>{f.feature} ({f.type}): PSI {f.psi ?? 'n/a'} — {f.level.replace(/_/g, ' ')}{f.reason ? ` (${f.reason})` : ''}</li>)}</ul>}
          <p className="mt-2 text-xs text-slate-500">Schema violations: {pct(dd.schema_violations.current_rate)} of records{dd.schema_violations.elevated ? ' — elevated' : ''}.</p>
        </Section>
        <Section title="Prediction (output) drift" status={pd.status} reason={pd.reason}>
          {pd.label_psi !== undefined && <p className="mt-2 text-xs text-slate-300">Label PSI {pd.label_psi ?? 'n/a'} · confidence PSI {pd.confidence_psi ?? 'n/a'}</p>}
        </Section>
        <Section title="Measured performance (labelled samples only)" status={perf.status} reason={perf.reason}>
          {perf.current && perf.reference && <p className="mt-2 text-xs text-slate-300">{perf.metric}: {perf.current.value} (n={perf.current.n}, 95% CI {perf.current.ci95[0]}–{perf.current.ci95[1]}) vs reference {perf.reference.value} (n={perf.reference.n}, CI {perf.reference.ci95[0]}–{perf.reference.ci95[1]})</p>}
          {perf.note && <p className="mt-1 text-xs text-slate-500">{perf.note}</p>}
        </Section>
        <Section title="Operational (inference jobs)" status={op.status} reason={op.reason}>
          {op.status === 'measured' && <p className="mt-2 text-xs text-slate-300">{op.finished_jobs} finished jobs · failure rate {op.failure_rate == null ? `not reported (${op.failure_rate_reason ?? 'too few jobs'})` : pct(op.failure_rate)}{op.duration_seconds ? ` · p50 ${op.duration_seconds.p50}s · p95 ${op.duration_seconds.p95}s (n=${op.duration_seconds.sample})` : ''}</p>}
        </Section>
      </div>
    </div>
  )
}

/** Monitoring dashboard: coverage, drift vs prediction drift vs performance vs operational, and activity. */
export function MonitoringDashboardPage() {
  const [coverage, setCoverage] = useState<Coverage | null>(null)
  const [summary, setSummary] = useState<ObservabilitySummary | null>(null)
  const [selected, setSelected] = useState<CoverageItem | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState(14)

  useEffect(() => { mlopsApi.coverage().then(setCoverage).catch((e) => setError(e.message)) }, [])
  useEffect(() => { setSummary(null); mlopsApi.summary(days).then(setSummary).catch((e) => setError(e.message)) }, [days])

  return (
    <div>
      <PageHeader title="Monitoring" description="Drift, performance and operational health are reported separately because they mean different things: a shifted input distribution is not by itself a drop in accuracy, and accuracy cannot be measured without labels. Monitoring snapshots are submitted through the API (POST /api/v1/mlops/monitoring/snapshots)." />
      {error && <ErrorState message={error} />}
      {!coverage && !error && <Spinner />}
      {coverage && (
        <>
          <div className="mb-4 grid gap-3 md:grid-cols-3">
            <StatTile label="Model versions in scope" value={coverage.models_total} hint="registered, in review or approved" />
            <StatTile label="With current monitoring" value={coverage.models_with_current_monitoring} hint={`latest window ended within ${coverage.freshness_days} days`} />
            <StatTile label="Without current monitoring" value={coverage.models_total - coverage.models_with_current_monitoring} hint="no snapshot, or stale" />
          </div>
          {coverage.models.length === 0 ? <EmptyState message="No model versions to monitor yet." /> : (
            <DataTable rows={coverage.models.map((m) => ({ ...m, id: m.model_record_id }))} onRowClick={setSelected} columns={[
              { header: 'Model', render: (m) => <Link className="text-accent-400" to={`/mlops/models/${m.model_record_id}`} onClick={(e) => e.stopPropagation()}>{m.name} {m.version}</Link> },
              { header: 'Coverage', render: (m) => <StatusPill status={m.coverage} /> },
              { header: 'Latest window ended', render: (m) => (m.latest_current_window_end ? `${fmtDate(m.latest_current_window_end)} (${m.age_days} d ago)` : 'never') },
              { header: 'Samples', render: (m) => m.latest_sample_count ?? '—' },
              { header: 'Reference', render: (m) => (m.has_reference ? 'yes' : 'none') },
            ]} />
          )}
          {selected && (
            <div className="mt-4">
              <h3 className="mb-2 text-sm font-semibold text-slate-100">{selected.name} {selected.version}</h3>
              {selected.latest_current_snapshot_id ? <DriftPanel item={selected} /> : <EmptyState message="No monitoring snapshot exists for this version, so nothing can be assessed. This is different from “no drift”." />}
            </div>
          )}
        </>
      )}
      <div className="mt-8">
        <div className="mb-2 flex items-center justify-between"><h3 className="text-sm font-semibold text-slate-100">Platform activity</h3>
          <select aria-label="Window" className="rounded-md border border-charcoal-600 bg-charcoal-900 px-2 py-1 text-xs text-slate-200" value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 14, 30].map((d) => <option key={d} value={d}>{d} days</option>)}</select></div>
        {!summary && !error && <Spinner />}
        {summary && (
          <div className="grid gap-4 md:grid-cols-2">
            <Card><DailyBars title="Inference jobs" unit="jobs" days={summary.window_days} rows={summary.inference_jobs.daily} failedKey="failed" />
              <p className="mt-2 text-xs text-slate-500">Failure rate: {summary.inference_jobs.failure_rate == null ? `not reported — ${summary.inference_jobs.failure_rate_note ?? 'too few jobs'}` : pct(summary.inference_jobs.failure_rate)}</p></Card>
            <Card><DailyBars title="Experiment runs" unit="runs" days={summary.window_days} rows={summary.experiment_runs.daily} failedKey="failed" /></Card>
            <Card className="md:col-span-2">
              <h4 className="mb-1 text-sm font-semibold text-slate-100">Not measured</h4>
              <ul className="list-disc pl-5 text-xs text-slate-500">{Object.entries(summary.unavailable).map(([k, v]) => <li key={k}><span className="text-slate-400">{k.replace(/_/g, ' ')}</span>: {v}</li>)}</ul>
            </Card>
          </div>
        )}
      </div>
    </div>
  )
}
