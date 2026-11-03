import type { HistoryPoint } from '../../types/mlops'

/**
 * Line chart of a metric across experiment runs. The caption always states the
 * metric, the window and the unit; points are real runs (hover for run id, n and
 * CI); synthetic-dataset runs are drawn hollow. No smoothing or interpolation
 * beyond joining consecutive points.
 */
export function MetricTrend({ metric, windowDays, points }: { metric: string; windowDays: number; points: HistoryPoint[] }) {
  const W = 560, H = 180, L = 44, R = 12, T = 12, B = 28
  const caption = `${metric} per experiment run, last ${windowDays} days · unit: proportion (0–1) · y-axis fixed 0–1`
  if (points.length === 0) {
    return <div className="rounded-md border border-dashed border-charcoal-600 px-4 py-8 text-center text-sm text-slate-500">No runs with a defined “{metric}” in the last {windowDays} days. Nothing is plotted.</div>
  }
  const t = points.map((p) => new Date(p.at).getTime())
  const t0 = Math.min(...t), t1 = Math.max(...t)
  const x = (i: number) => (t1 === t0 ? (L + W - R) / 2 : L + ((t[i] - t0) / (t1 - t0)) * (W - L - R))
  const y = (v: number) => T + (1 - Math.min(1, Math.max(0, v))) * (H - T - B)
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={caption} className="w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((g) => (
          <g key={g}>
            <line x1={L} x2={W - R} y1={y(g)} y2={y(g)} stroke="currentColor" className="text-charcoal-700" strokeWidth={1} />
            <text x={L - 6} y={y(g) + 3} textAnchor="end" className="fill-slate-500" fontSize={10}>{g}</text>
          </g>
        ))}
        {points.map((p, i) => p.ci95 && (
          <line key={`ci-${p.run_id}`} x1={x(i)} x2={x(i)} y1={y(p.ci95[0])} y2={y(p.ci95[1])} stroke="currentColor" className="text-slate-600" strokeWidth={2} />
        ))}
        <path d={path} fill="none" stroke="currentColor" className="text-accent-400" strokeWidth={1.5} />
        {points.map((p, i) => (
          <circle key={p.run_id} cx={x(i)} cy={y(p.value)} r={4} strokeWidth={2} stroke="currentColor"
            className={`text-accent-400 ${p.is_synthetic ? 'fill-navy-950' : 'fill-accent-400'}`}>
            <title>{`${p.model_version} · ${p.value.toFixed(4)}${p.n != null ? ` · n=${p.n}` : ''}${p.ci95 ? ` · 95% CI ${p.ci95[0].toFixed(3)}–${p.ci95[1].toFixed(3)}` : ''} · ${p.dataset}${p.is_synthetic ? ' (synthetic)' : ''} · ${new Date(p.at).toLocaleString()}`}</title>
          </circle>
        ))}
        <text x={L} y={H - 8} className="fill-slate-500" fontSize={10}>{new Date(t0).toLocaleDateString()}</text>
        <text x={W - R} y={H - 8} textAnchor="end" className="fill-slate-500" fontSize={10}>{new Date(t1).toLocaleDateString()}</text>
      </svg>
      <figcaption className="mt-1 text-xs text-slate-500">{caption}. Hollow points are synthetic datasets. Vertical bars are 95% Wilson intervals where defined.</figcaption>
    </figure>
  )
}
