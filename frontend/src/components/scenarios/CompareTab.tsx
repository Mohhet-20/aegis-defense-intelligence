import { useEffect, useMemo, useState } from 'react'
import { scenarioApi } from '../../api/scenarios'
import { LoadState, Notice } from '../investigations/InvestigationBits'
import { errorText, fmtTime, useLoad } from '../investigations/useLoad'
import { Button, Card, EmptyState, Field, inputClass } from '../ui/Primitives'
import { BarChart, SyntheticBanner } from './ScenarioBits'
import { fmt } from './scenarioUtils'
import type { Comparison, RunSummary, Scenario } from '../../types/scenario'

interface Cand { run: RunSummary; label: string }

export function CompareTab({ scenario }: { scenario: Scenario }) {
  // Candidate runs: completed simulation runs from every version in this scenario's lineage.
  const cands = useLoad(async () => {
    const versions = await scenarioApi.versions(scenario.id)
    const out: Cand[] = []
    for (const v of versions) {
      const page = await scenarioApi.runs(v.id, { status: 'completed', kind: 'simulation' })
      for (const r of page.items) out.push({ run: r, label: `v${v.version} - seed ${r.seed} - ${fmtTime(r.completed_at)} - ${r.id.slice(0, 8)}` })
    }
    return out
  }, [scenario.id])
  const [base, setBase] = useState('')
  const [alts, setAlts] = useState<string[]>([''])
  const [result, setResult] = useState<Comparison | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [metric, setMetric] = useState('')

  useEffect(() => { setResult(null) }, [base, alts])
  const labelOf = useMemo(() => new Map((cands.data ?? []).map((c) => [c.run.id, c.label])), [cands.data])
  const chosen = alts.filter(Boolean)

  async function go() {
    setBusy(true)
    setError(null)
    try {
      const r = await scenarioApi.compare(base, chosen)
      setResult(r)
      setMetric(r.alternatives[0]?.metrics.find((m) => m.comparable)?.name ?? '')
    } catch (e) { setError(errorText(e, 'Comparison failed')) } finally { setBusy(false) }
  }

  const options = (exclude: string[]) => (cands.data ?? []).filter((c) => !exclude.includes(c.run.id))
  return (
    <div>
      <SyntheticBanner>Comparisons describe how two SIMULATED runs differ. They show an association within the experiment, not a real-world causal effect.</SyntheticBanner>
      <LoadState loading={cands.loading} error={cands.error}>
        {(cands.data ?? []).length < 2 ? (
          <EmptyState message="Comparison needs at least two completed simulation runs (run this scenario, or duplicate it into a new version with a changed parameter and run that too)." />
        ) : (
          <Card>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <Field label="Baseline run">
                <select className={inputClass} value={base} onChange={(e) => setBase(e.target.value)}>
                  <option value="">Select baseline</option>
                  {options(chosen).map((c) => <option key={c.run.id} value={c.run.id}>{c.label}</option>)}
                </select>
              </Field>
              <div className="space-y-2">
                {alts.map((a, i) => (
                  <Field key={i} label={`Alternative run ${i + 1}`}>
                    <select className={inputClass} value={a} onChange={(e) => setAlts(alts.map((x, j) => (j === i ? e.target.value : x)))}>
                      <option value="">Select alternative</option>
                      {options([base, ...alts.filter((_, j) => j !== i)]).map((c) => <option key={c.run.id} value={c.run.id}>{c.label}</option>)}
                    </select>
                  </Field>
                ))}
                {alts.length < 3 && <Button variant="secondary" onClick={() => setAlts([...alts, ''])}>Add alternative (max 3)</Button>}
              </div>
            </div>
            <div className="mt-3"><Button disabled={!base || chosen.length === 0 || busy} onClick={go}>{busy ? 'Comparing...' : 'Compare'}</Button></div>
          </Card>
        )}
      </LoadState>
      {error && <Notice tone="warn">{error}</Notice>}
      {result && (
        <div className="mt-4 space-y-4">
          {result.caveats.map((c) => <Notice key={c}>{c}</Notice>)}
          {result.alternatives.map((a) => {
            const chartable = a.metrics.filter((m) => m.comparable)
            const sel = a.metrics.find((m) => m.name === metric) ?? chartable[0]
            return (
              <Card key={a.run_id}>
                <h3 className="mb-1 text-sm font-semibold text-slate-100">Alternative <span className="font-mono text-xs">{labelOf.get(a.run_id) ?? a.run_id}</span></h3>
                <Notice tone={a.attribution.status === 'single_parameter' ? 'info' : 'warn'}>{a.attribution.statement}</Notice>
                {a.warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Parameters that changed</h4>
                    {a.parameter_changes.length === 0 && !a.seed_changed ? <p className="text-xs text-slate-500">None.</p> : (
                      <table className="text-sm"><caption className="sr-only">Changed parameters</caption>
                        <thead><tr className="text-xs text-slate-500"><th scope="col" className="pr-4 text-left">Parameter</th><th scope="col" className="pr-4 text-left">Baseline</th><th scope="col" className="text-left">Alternative</th></tr></thead>
                        <tbody>
                          {a.parameter_changes.map((c) => <tr key={c.param}><th scope="row" className="pr-4 text-left font-mono text-xs font-normal">{c.param}</th><td className="pr-4">{fmt(c.baseline)}</td><td>{fmt(c.alternative)}</td></tr>)}
                          {a.seed_changed && <tr><th scope="row" className="pr-4 text-left font-normal text-amber-400">random seed</th><td colSpan={2} className="text-xs text-slate-400">differs (counts as a changed input)</td></tr>}
                        </tbody>
                      </table>
                    )}
                  </div>
                  <div>
                    <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Held constant</h4>
                    <p className="text-xs text-slate-400">{a.held_constant.map((h) => `${h.param}=${fmt(h.value)}`).join(', ') || 'none'}</p>
                  </div>
                </div>
                <h4 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Metric comparison</h4>
                {a.metrics.length === 0 ? <p className="text-xs text-slate-500">No metrics are comparable.</p> : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm"><caption className="sr-only">Metric comparison between baseline and alternative</caption>
                      <thead><tr className="text-xs uppercase text-slate-500"><th scope="col" className="py-1 pr-3">Metric</th><th scope="col" className="pr-3">Unit</th><th scope="col" className="pr-3">Baseline</th><th scope="col" className="pr-3">Alternative</th><th scope="col" className="pr-3">Abs. diff</th><th scope="col" className="pr-3">Rel. diff</th><th scope="col">Note</th></tr></thead>
                      <tbody>
                        {a.metrics.map((m) => (
                          <tr key={m.name} className="border-t border-charcoal-700/60">
                            <th scope="row" className="py-1 pr-3 font-mono text-xs font-normal">{m.name}</th><td className="pr-3 text-slate-400">{m.unit}</td>
                            <td className="pr-3">{fmt(m.baseline)}</td><td className="pr-3">{fmt(m.alternative)}</td>
                            <td className="pr-3">{m.absolute_diff === null ? 'n/a' : fmt(m.absolute_diff)}</td>
                            <td className="pr-3">{m.relative_diff === null ? 'n/a' : `${fmt(m.relative_diff * 100, 2)}%`}</td>
                            <td className="text-xs text-slate-500">{m.reason ?? (m.comparable ? '' : 'incomparable')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {chartable.length > 0 && sel && (
                  <div className="mt-3">
                    <Field label="Chart metric">
                      <select className={inputClass} value={sel.name} onChange={(e) => setMetric(e.target.value)}>{chartable.map((m) => <option key={m.name} value={m.name}>{m.name} ({m.unit})</option>)}</select>
                    </Field>
                    <BarChart title={`${sel.name}: baseline vs alternative`} unit={sel.unit} groups={[{ label: 'baseline', value: sel.baseline }, { label: 'alternative', value: sel.alternative }]} />
                  </div>
                )}
              </Card>
            )
          })}
          <Card>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Assumptions behind the comparison</h4>
            <ul className="list-disc pl-5 text-xs text-slate-400">{result.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
            <h4 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Limitations</h4>
            <ul className="list-disc pl-5 text-xs text-slate-400">{result.limitations.map((a) => <li key={a}>{a}</li>)}</ul>
          </Card>
        </div>
      )}
    </div>
  )
}
