import { useState } from 'react'
import { scenarioApi } from '../../api/scenarios'
import { LoadState, Mono, Notice } from '../investigations/InvestigationBits'
import { errorText, fmtTime, useLoad } from '../investigations/useLoad'
import { Button, Card, StatusPill } from '../ui/Primitives'
import { MetricsTable, SimBadge, SyntheticBanner } from './ScenarioBits'
import { fmt } from './scenarioUtils'
import type { MetricDoc, RunDetail } from '../../types/scenario'

/** Everything stored about one run: configuration snapshot, versions, seed, timeline, errors, outputs. */
export function RunPanel({ runId, metricDocs, canRun, onRetried }: { runId: string; metricDocs: MetricDoc[]; canRun: boolean; onRetried: (r: RunDetail) => void }) {
  const run = useLoad(() => scenarioApi.runDetail(runId), [runId])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function retry(r: RunDetail) {
    setBusy(true)
    setErr(null)
    try { onRetried(await scenarioApi.retry(r.id)) } catch (e) { setErr(errorText(e, 'Retry failed')) } finally { setBusy(false) }
  }

  return (
    <LoadState loading={run.loading} error={run.error}>
      {run.data && (() => {
        const r = run.data
        const snap = r.config_snapshot
        const res = r.results
        return (
          <Card className="mt-4">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-slate-100">Run <Mono>{r.id}</Mono></h3>
              <StatusPill status={r.status} /><SimBadge />
              <span className="text-xs text-slate-500">{r.run_kind}</span>
            </div>
            <SyntheticBanner />
            {err && <Notice tone="warn">{err}</Notice>}
            {r.status === 'failed' && (
              <Notice tone="warn">
                This run FAILED ({r.error_code}): {r.error_message} No results were stored.{' '}
                {canRun && <Button variant="secondary" disabled={busy} onClick={() => retry(r)}>{busy ? 'Retrying...' : 'Retry (creates a new run)'}</Button>}
              </Notice>
            )}
            <h4 className="mb-1 mt-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Execution log (from stored fields)</h4>
            <table className="mb-3 text-sm">
              <caption className="sr-only">Execution timeline</caption>
              <tbody>
                <tr><th scope="row" className="pr-4 text-left font-normal text-slate-500">Started</th><td className="text-slate-300">{fmtTime(r.started_at)}</td></tr>
                <tr><th scope="row" className="pr-4 text-left font-normal text-slate-500">{r.status === 'running' ? 'Still running' : r.status === 'failed' ? 'Failed' : 'Completed'}</th><td className="text-slate-300">{r.completed_at ? fmtTime(r.completed_at) : 'not finished'}</td></tr>
                <tr><th scope="row" className="pr-4 text-left font-normal text-slate-500">Measured runtime</th><td className="text-slate-300">{r.runtime_ms === null ? 'not recorded' : `${r.runtime_ms} ms`}</td></tr>
                {r.retry_of_run_id && <tr><th scope="row" className="pr-4 text-left font-normal text-slate-500">Retry of</th><td><Mono>{r.retry_of_run_id}</Mono></td></tr>}
                {r.idempotent_replay && <tr><td colSpan={2} className="text-xs text-slate-500">This response was an idempotent replay of an earlier request.</td></tr>}
              </tbody>
            </table>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Reproducibility</h4>
            <table className="mb-3 text-sm">
              <caption className="sr-only">Reproducibility information</caption>
              <tbody>
                <tr><th scope="row" className="pr-4 text-left font-normal text-slate-500">Scenario / version</th><td className="text-slate-300"><Mono>{r.scenario_id}</Mono> v{r.scenario_version}</td></tr>
                <tr><th scope="row" className="pr-4 text-left font-normal text-slate-500">Simulator</th><td className="text-slate-300">{r.simulator_id} v{r.simulator_version}</td></tr>
                <tr><th scope="row" className="pr-4 text-left font-normal text-slate-500">Seed</th><td className="text-slate-300">{r.seed}</td></tr>
                <tr><th scope="row" className="pr-4 text-left font-normal text-slate-500">Result SHA-256</th><td>{r.result_sha256 ? <Mono>{r.result_sha256}</Mono> : 'none (no result stored)'}</td></tr>
                {r.dataset_ref && <tr><th scope="row" className="pr-4 text-left font-normal text-slate-500">Synthetic data</th><td className="text-xs text-slate-300">generator {String(r.dataset_ref.generator)} v{String(r.dataset_ref.generator_version)}, seed {String(r.dataset_ref.seed)}, {String(r.dataset_ref.record_count)} records, hash <Mono>{String(r.dataset_ref.content_sha256)}</Mono></td></tr>}
              </tbody>
            </table>
            <p className="mb-3 text-xs text-slate-500">Re-running with the same scenario version, parameters and seed reproduces this result exactly (same hash).</p>
            <details className="mb-3"><summary className="cursor-pointer text-xs text-slate-400">Configuration snapshot</summary>
              <pre className="mt-2 max-h-64 overflow-auto rounded-sm bg-charcoal-900 p-3 text-xs text-slate-300">{JSON.stringify(snap, null, 2)}</pre>
            </details>
            {res && r.run_kind === 'simulation' && (
              <>
                <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Simulated metrics</h4>
                <MetricsTable metrics={res.metrics} docs={metricDocs} />
                {res.notes.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs text-slate-500">{res.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
                {res.dataset_header && (
                  <p className="mt-2 text-xs text-slate-500">
                    Synthetic input: {res.dataset_header.record_count} records, {res.dataset_header.n_dropped_missing} dropped as missing, {res.dataset_header.n_duplicates} duplicates, {res.dataset_header.n_outliers} injected outliers.
                    Limitations: {res.dataset_header.limitations.join(' ')}
                  </p>
                )}
                {res.preview.length > 0 && (
                  <details className="mt-2"><summary className="cursor-pointer text-xs text-slate-400">Preview of simulated records ({Math.min(res.preview.length, 20)} of {res.preview.length} shown; all marked synthetic)</summary>
                    <div className="mt-2 overflow-x-auto"><table className="text-xs text-slate-300"><caption className="sr-only">Preview of simulated records</caption>
                      <thead><tr>{Object.keys(res.preview[0]).map((k) => <th key={k} scope="col" className="pr-3 text-left font-medium text-slate-500">{k}</th>)}</tr></thead>
                      <tbody>{res.preview.slice(0, 20).map((row, i) => <tr key={i}>{Object.values(row).map((v, j) => <td key={j} className="pr-3">{fmt(v)}</td>)}</tr>)}</tbody>
                    </table></div>
                  </details>
                )}
              </>
            )}
            {res && r.run_kind === 'sensitivity' && <p className="text-xs text-slate-500">Sensitivity results are shown in the Sensitivity tab. Planned/executed simulations: {String(res.total_runs)}.</p>}
            <h4 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Assumptions and limitations recorded with this run</h4>
            <ul className="list-disc pl-5 text-xs text-slate-400">{snap.assumptions.map((a) => <li key={a}>Assumption: {a}</li>)}{snap.limitations.map((a) => <li key={a}>Limitation: {a}</li>)}</ul>
          </Card>
        )
      })()}
    </LoadState>
  )
}
