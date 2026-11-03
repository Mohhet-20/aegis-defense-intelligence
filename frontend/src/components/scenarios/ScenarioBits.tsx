import type { ReactNode } from 'react'
import { Notice } from '../investigations/InvestigationBits'
import { inputClass } from '../ui/Primitives'
import type { MetricDoc, Metrics, ParamDoc, ParamValues } from '../../types/scenario'
import { SIM_NOTICE, fmt, rangeText } from './scenarioUtils'

export function SyntheticBanner({ children }: { children?: ReactNode }) {
  return (
    <div role="note" aria-label="Simulated data notice">
      <Notice tone="warn">
        <strong>SIMULATED / SYNTHETIC.</strong> {children ?? SIM_NOTICE}
      </Notice>
    </div>
  )
}

export function SimBadge() {
  return (
    <span className="inline-block rounded-sm border border-status-warning/40 bg-status-warning/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-status-warning">
      simulated
    </span>
  )
}

/** Typed parameter inputs generated from the simulator's own parameter docs. */
export function ParamEditor({
  specs, values, onChange, disabled,
}: { specs: ParamDoc[]; values: ParamValues; onChange: (v: ParamValues) => void; disabled?: boolean }) {
  const set = (name: string, v: number | boolean | string) => onChange({ ...values, [name]: v })
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {specs.map((p) => {
        const id = `param-${p.name}`
        const val = values[p.name] ?? p.default ?? ''
        return (
          <div key={p.name}>
            <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-300">
              {p.name} <span className="font-normal text-slate-500">({p.type}; {rangeText(p)}; default {fmt(p.default)})</span>
            </label>
            {p.type === 'bool' ? (
              <input id={id} type="checkbox" disabled={disabled} checked={Boolean(val)} onChange={(e) => set(p.name, e.target.checked)} />
            ) : p.type === 'choice' ? (
              <select id={id} disabled={disabled} className={inputClass} value={String(val)} onChange={(e) => set(p.name, e.target.value)}>
                {(p.choices ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            ) : (
              <input
                id={id} type="number" disabled={disabled} className={inputClass} value={String(val)}
                min={p.min ?? undefined} max={p.max ?? undefined} step={p.type === 'int' ? 1 : 'any'}
                onChange={(e) => set(p.name, e.target.value === '' ? NaN : Number(e.target.value))}
                aria-describedby={`${id}-help`}
              />
            )}
            <p id={`${id}-help`} className="mt-0.5 text-[11px] text-slate-500">{p.description}</p>
          </div>
        )
      })}
    </div>
  )
}

/** Accessible metric table with units and descriptions (the text alternative to every chart). */
export function MetricsTable({ metrics, docs }: { metrics: Metrics; docs: MetricDoc[] }) {
  const by = new Map(docs.map((d) => [d.name, d]))
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Simulated metrics</caption>
        <thead><tr className="text-xs uppercase text-slate-500"><th scope="col" className="py-1 pr-4">Metric</th><th scope="col" className="py-1 pr-4">Value</th><th scope="col" className="py-1 pr-4">Unit</th><th scope="col" className="py-1">Meaning</th></tr></thead>
        <tbody>
          {Object.entries(metrics).map(([k, v]) => (
            <tr key={k} className="border-t border-charcoal-700/60 align-top">
              <th scope="row" className="py-1 pr-4 font-mono text-xs font-normal text-slate-300">{k}</th>
              <td className="py-1 pr-4 text-slate-200">{fmt(v)}{v === null && <span className="ml-1 text-[11px] text-slate-500">(not defined for this run)</span>}</td>
              <td className="py-1 pr-4 text-slate-400">{by.get(k)?.unit ?? ''}</td>
              <td className="py-1 text-xs text-slate-500">{by.get(k)?.description ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const COLORS = ['#38bdf8', '#f59e0b', '#a78bfa', '#34d399']

/** Grouped bar chart (inline SVG). The parent must render the same numbers as a table. */
export function BarChart({ title, unit, groups }: { title: string; unit: string; groups: { label: string; value: number | null }[] }) {
  const defined = groups.filter((g) => g.value !== null) as { label: string; value: number }[]
  if (!defined.length) return <p className="text-xs text-slate-500">No defined values to chart.</p>
  const max = Math.max(...defined.map((g) => g.value), 0)
  const min = Math.min(...defined.map((g) => g.value), 0)
  const span = max - min || 1
  const W = 420, H = 180, pad = 36
  const bw = Math.min(60, (W - pad * 2) / groups.length - 12)
  const y = (v: number) => H - pad - ((v - min) / span) * (H - pad * 2)
  return (
    <svg role="img" aria-label={`${title} (${unit}). Values are in the table below.`} viewBox={`0 0 ${W} ${H}`} className="w-full max-w-xl">
      <title>{title}</title>
      <line x1={pad} x2={W - pad / 2} y1={y(0)} y2={y(0)} stroke="#64748b" strokeWidth="1" />
      {groups.map((g, i) => {
        const x = pad + 8 + i * ((W - pad * 2) / groups.length)
        if (g.value === null) return <text key={g.label} x={x} y={y(0) - 4} fontSize="9" fill="#94a3b8">n/a</text>
        const top = Math.min(y(g.value), y(0)), h = Math.abs(y(g.value) - y(0))
        return (
          <g key={g.label}>
            <rect x={x} y={top} width={bw} height={Math.max(h, 1)} fill={COLORS[i % COLORS.length]} />
            <text x={x + bw / 2} y={top - 3} fontSize="9" textAnchor="middle" fill="#cbd5e1">{fmt(g.value, 3)}</text>
            <text x={x + bw / 2} y={H - 8} fontSize="9" textAnchor="middle" fill="#94a3b8">{g.label.slice(0, 14)}</text>
          </g>
        )
      })}
      <text x={4} y={12} fontSize="9" fill="#94a3b8">{unit}</text>
    </svg>
  )
}

export interface LinePoint { x: number; y: number | null; lo?: number | null; hi?: number | null }

/** Line chart of a metric's mean across tested values (+ empirical p10-p90 band when available). */
export function LineChart({ title, xLabel, yLabel, points }: { title: string; xLabel: string; yLabel: string; points: LinePoint[] }) {
  const ok = points.filter((p) => p.y !== null) as (LinePoint & { y: number })[]
  if (ok.length < 2) return <p className="text-xs text-slate-500">Not enough defined values to chart.</p>
  const xs = ok.map((p) => p.x)
  const ys = ok.flatMap((p) => [p.y, p.lo ?? p.y, p.hi ?? p.y])
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
  const W = 420, H = 190, pl = 44, pb = 30, pt = 14, pr = 10
  const sx = (v: number) => pl + ((v - x0) / (x1 - x0 || 1)) * (W - pl - pr)
  const sy = (v: number) => H - pb - ((v - y0) / (y1 - y0 || 1)) * (H - pb - pt)
  const band = ok.every((p) => p.lo !== undefined && p.lo !== null && p.hi !== undefined && p.hi !== null)
  return (
    <svg role="img" aria-label={`${title}: ${yLabel} against ${xLabel}. Values are in the table below.`} viewBox={`0 0 ${W} ${H}`} className="w-full max-w-xl">
      <title>{title}</title>
      <line x1={pl} x2={pl} y1={pt} y2={H - pb} stroke="#475569" />
      <line x1={pl} x2={W - pr} y1={H - pb} y2={H - pb} stroke="#475569" />
      {band && <polygon fill="#38bdf8" opacity="0.15" points={[...ok.map((p) => `${sx(p.x)},${sy(p.hi as number)}`), ...[...ok].reverse().map((p) => `${sx(p.x)},${sy(p.lo as number)}`)].join(' ')} />}
      <polyline fill="none" stroke="#38bdf8" strokeWidth="2" points={ok.map((p) => `${sx(p.x)},${sy(p.y)}`).join(' ')} />
      {ok.map((p) => <circle key={p.x} cx={sx(p.x)} cy={sy(p.y)} r="3" fill="#38bdf8" />)}
      <text x={pl} y={H - 8} fontSize="9" fill="#94a3b8">{fmt(x0, 3)}</text>
      <text x={W - pr} y={H - 8} fontSize="9" textAnchor="end" fill="#94a3b8">{fmt(x1, 3)}</text>
      <text x={W / 2} y={H - 8} fontSize="9" textAnchor="middle" fill="#94a3b8">{xLabel}</text>
      <text x={pl - 4} y={sy(y1) + 3} fontSize="9" textAnchor="end" fill="#94a3b8">{fmt(y1, 3)}</text>
      <text x={pl - 4} y={sy(y0) + 3} fontSize="9" textAnchor="end" fill="#94a3b8">{fmt(y0, 3)}</text>
    </svg>
  )
}

