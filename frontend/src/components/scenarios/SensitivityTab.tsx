import { useMemo, useState } from 'react'
import { scenarioApi } from '../../api/scenarios'
import { LoadState, Notice } from '../investigations/InvestigationBits'
import { errorText, fmtTime, useLoad } from '../investigations/useLoad'
import { Button, Card, EmptyState, Field, inputClass } from '../ui/Primitives'
import { LineChart, SyntheticBanner } from './ScenarioBits'
import { fmt } from './scenarioUtils'
import type { RunDetail, Scenario, SensitivityResult, SimulatorDoc, SweepEntryInput } from '../../types/scenario'

interface Row { param: string; min: string; max: string; steps: string }
const MAX_PARAMS = 4, MAX_STEPS = 9, MAX_REPS = 20, MAX_RUNS = 200

function ResultView({ res }: { res: SensitivityResult }) {
  return (
    <div className="mt-4 space-y-4">
      <Card>
        <h3 className="mb-1 text-sm font-semibold text-slate-100">Method: one parameter at a time</h3>
        <ul className="list-disc pl-5 text-xs text-slate-400">{res.interpretation.map((i) => <li key={i}>{i}</li>)}</ul>
        <p className="mt-2 text-xs text-slate-500">
          Metric: <span className="font-mono">{res.metric}</span> ({res.metric_unit}). {res.repetitions} repetitions per setting with seeds {res.seeds.join(', ')}; {res.total_runs} simulations executed
          (limits: {res.limits.max_params} parameters, {res.limits.max_values} values each, {res.limits.max_reps} repetitions, {res.limits.max_total_runs} total).
        </p>
      </Card>
      <Card>
        <h3 className="mb-2 text-sm font-semibold text-slate-100">Parameters ranked by observed effect range</h3>
        {res.ranking.length === 0 ? <p className="text-xs text-slate-500">No parameter produced a defined metric across its tested values.</p> : (
          <table className="w-full text-left text-sm"><caption className="sr-only">Ranking of parameters by effect range</caption>
            <thead><tr className="text-xs uppercase text-slate-500"><th scope="col" className="py-1 pr-4">Rank</th><th scope="col" className="pr-4">Parameter</th><th scope="col" className="pr-4">Effect range ({res.metric_unit})</th><th scope="col">Larger than 2x baseline seed-to-seed sd (rough heuristic, not a test)</th></tr></thead>
            <tbody>{res.ranking.map((r, i) => (
              <tr key={r.param} className="border-t border-charcoal-700/60"><td className="py-1 pr-4">{i + 1}</td><th scope="row" className="pr-4 font-mono text-xs font-normal">{r.param}</th><td className="pr-4">{fmt(r.effect_range)}</td><td>{r.exceeds_baseline_seed_variability === null ? 'not computable' : r.exceeds_baseline_seed_variability ? 'yes' : 'no'}</td></tr>
            ))}</tbody>
          </table>
        )}
      </Card>
      {res.parameters.map((p) => (
        <Card key={p.param}>
          <h3 className="mb-2 text-sm font-semibold text-slate-100"><span className="font-mono">{p.param}</span> {p.unit && <span className="text-xs font-normal text-slate-500">({p.unit})</span>}</h3>
          <LineChart
            title={`${res.metric} across tested ${p.param} values`} xLabel={p.param} yLabel={`${res.metric} (${res.metric_unit})`}
            points={p.points.map((pt) => ({ x: pt.value, y: pt.metric_summary.mean, lo: pt.metric_summary.p10, hi: pt.metric_summary.p90 }))}
          />
          <p className="mb-2 text-[11px] text-slate-500">Line = mean over repetitions. Shaded band (only when at least 5 repetitions) = empirical 10th-90th percentile across seeds; it is variability of the simulated outcome, not a confidence interval.</p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm"><caption className="sr-only">{`Summary of ${res.metric} for each tested value of ${p.param}`}</caption>
              <thead><tr className="text-xs uppercase text-slate-500"><th scope="col" className="py-1 pr-3">{p.param}</th><th scope="col" className="pr-3">n</th><th scope="col" className="pr-3">undefined</th><th scope="col" className="pr-3">mean</th><th scope="col" className="pr-3">sd</th><th scope="col" className="pr-3">min</th><th scope="col" className="pr-3">p10</th><th scope="col" className="pr-3">p50</th><th scope="col" className="pr-3">p90</th><th scope="col">max</th></tr></thead>
              <tbody>{p.points.map((pt) => {
                const s = pt.metric_summary
                return <tr key={pt.value} className="border-t border-charcoal-700/60"><th scope="row" className="py-1 pr-3 font-normal">{fmt(pt.value)}</th><td className="pr-3">{s.n}</td><td className="pr-3">{s.n_undefined}</td><td className="pr-3">{fmt(s.mean)}</td><td className="pr-3">{fmt(s.sd)}</td><td className="pr-3">{fmt(s.min)}</td><td className="pr-3">{fmt(s.p10)}</td><td className="pr-3">{fmt(s.p50)}</td><td className="pr-3">{fmt(s.p90)}</td><td>{fmt(s.max)}</td></tr>
              })}</tbody>
            </table>
          </div>
        </Card>
      ))}
      <Card>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Assumptions and limitations</h4>
        <ul className="list-disc pl-5 text-xs text-slate-400">{res.assumptions.map((a) => <li key={a}>{a}</li>)}{res.limitations.map((a) => <li key={a}>Limitation: {a}</li>)}</ul>
      </Card>
    </div>
  )
}

export function SensitivityTab({ scenario, sim, canRun }: { scenario: Scenario; sim: SimulatorDoc; canRun: boolean }) {
  const numeric = sim.parameters.filter((p) => (p.type === 'int' || p.type === 'float') && p.min !== null && p.max !== null)
  const [rows, setRows] = useState<Row[]>([])
  const [metric, setMetric] = useState(sim.metrics[0]?.name ?? '')
  const [reps, setReps] = useState(5)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [viewing, setViewing] = useState<RunDetail | null>(null)
  const past = useLoad(() => scenarioApi.runs(scenario.id, { kind: 'sensitivity' }), [scenario.id, viewing?.id])

  const planned = useMemo(() => reps + rows.reduce((n, r) => n + (Number(r.steps) || 0) * reps, 0), [rows, reps])
  const rowProblem = (r: Row) => {
    const spec = numeric.find((p) => p.name === r.param)
    const lo = Number(r.min), hi = Number(r.max), st = Number(r.steps)
    if (!spec) return 'choose a parameter'
    if (r.min === '' || r.max === '' || !(hi > lo)) return 'max must be greater than min'
    if (lo < (spec.min as number) || hi > (spec.max as number)) return `must stay within ${spec.min} to ${spec.max}`
    if (!Number.isInteger(st) || st < 2 || st > MAX_STEPS) return `steps must be a whole number from 2 to ${MAX_STEPS}`
    return null
  }
  const problems = rows.map(rowProblem)
  const valid = rows.length > 0 && problems.every((p) => p === null) && new Set(rows.map((r) => r.param)).size === rows.length && planned <= MAX_RUNS && reps >= 1 && reps <= MAX_REPS

  async function go() {
    setBusy(true)
    setError(null)
    try {
      const sweep: SweepEntryInput[] = rows.map((r) => ({ param: r.param, min: Number(r.min), max: Number(r.max), steps: Number(r.steps) }))
      setViewing(await scenarioApi.sensitivity(scenario.id, { sweep, repetitions: reps, metric }))
    } catch (e) { setError(errorText(e, 'Sensitivity analysis failed')) } finally { setBusy(false) }
  }

  return (
    <div>
      <SyntheticBanner>Sensitivity analysis varies inputs of a SIMULATION. Spread across random seeds is variability of simulated outcomes, not uncertainty about the real world; no confidence intervals are computed.</SyntheticBanner>
      {scenario.status !== 'ready' ? (
        <EmptyState message="Sensitivity analysis needs a scenario that is marked ready." />
      ) : canRun ? (
        <Card>
          <h3 className="mb-2 text-sm font-semibold text-slate-100">Configure a one-parameter-at-a-time sweep</h3>
          <p className="mb-3 text-xs text-slate-500">Each chosen parameter is varied alone over evenly spaced values while all others stay at this scenario&apos;s settings. Interactions are not explored. Limits: {MAX_PARAMS} parameters, {MAX_STEPS} values each, {MAX_REPS} repetitions, {MAX_RUNS} simulations in total.</p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <Field label="Metric to analyse"><select className={inputClass} value={metric} onChange={(e) => setMetric(e.target.value)}>{sim.metrics.map((m) => <option key={m.name} value={m.name}>{m.name} ({m.unit})</option>)}</select></Field>
            <Field label={`Repetitions per setting (1-${MAX_REPS}; different seeds)`}><input className={inputClass} type="number" min={1} max={MAX_REPS} value={reps} onChange={(e) => setReps(Number(e.target.value))} /></Field>
          </div>
          {rows.map((r, i) => (
            <div key={i} className="mt-3 grid grid-cols-2 items-end gap-2 md:grid-cols-5">
              <Field label="Parameter">
                <select className={inputClass} value={r.param} onChange={(e) => {
                  const spec = numeric.find((p) => p.name === e.target.value)
                  setRows(rows.map((x, j) => (j === i ? { param: e.target.value, min: String(spec?.min ?? ''), max: String(spec?.max ?? ''), steps: '3' } : x)))
                }}>
                  <option value="">Select</option>{numeric.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
                </select>
              </Field>
              {(['min', 'max', 'steps'] as const).map((k) => (
                <Field key={k} label={k}><input className={inputClass} type="number" value={r[k]} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))} /></Field>
              ))}
              <Button variant="secondary" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</Button>
              {problems[i] && r.param && <p className="col-span-full text-xs text-status-warning">{problems[i]}</p>}
            </div>
          ))}
          {rows.length < MAX_PARAMS && <div className="mt-3"><Button variant="secondary" onClick={() => setRows([...rows, { param: '', min: '', max: '', steps: '3' }])}>Add parameter</Button></div>}
          <p className={`mt-3 text-xs ${planned > MAX_RUNS ? 'text-status-warning' : 'text-slate-500'}`}>Planned simulations: {planned} (baseline repetitions + values x repetitions) of {MAX_RUNS} allowed.</p>
          {error && <Notice tone="warn">{error}</Notice>}
          <div className="mt-3"><Button disabled={!valid || busy} onClick={go}>{busy ? 'Running analysis...' : 'Run sensitivity analysis'}</Button></div>
        </Card>
      ) : <Notice>Your role can view sensitivity results but cannot start an analysis.</Notice>}

      {viewing?.status === 'failed' && <Notice tone="warn">The analysis failed ({viewing.error_code}): {viewing.error_message}</Notice>}
      {viewing?.status === 'completed' && viewing.results?.method && <ResultView res={viewing.results as unknown as SensitivityResult} />}

      <h3 className="mb-2 mt-6 text-sm font-semibold text-slate-100">Previous sensitivity analyses</h3>
      <LoadState loading={past.loading} error={past.error}>
        {past.data && past.data.items.length === 0 ? <EmptyState message="No sensitivity analyses have been run for this scenario version." /> : (
          <ul className="space-y-1 text-sm">
            {past.data?.items.map((r) => (
              <li key={r.id}>
                <button type="button" className="text-accent-400 hover:underline" onClick={async () => setViewing(await scenarioApi.runDetail(r.id))}>
                  {fmtTime(r.started_at)} - {r.status}{r.error_code ? ` (${r.error_code})` : ''} - seed {r.seed}
                </button>
              </li>
            ))}
          </ul>
        )}
      </LoadState>
    </div>
  )
}
