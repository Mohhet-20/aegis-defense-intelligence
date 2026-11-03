/** Accessible, labelled SVG charts. Every chart states what is plotted, the unit and the window in its caption. */
const W = 560

export function BarSeries({ title, unit, windowText, rows }: { title: string; unit: string; windowText: string; rows: [string, number][] }) {
  const total = rows.reduce((a, r) => a + r[1], 0)
  const caption = `${title} · unit: ${unit} · ${windowText}`
  if (rows.length === 0 || total === 0) {
    return <div role="img" aria-label={`${caption}: no records`} className="rounded-md border border-dashed border-charcoal-600 px-4 py-6 text-center text-xs text-slate-500">{title}: no stored records in this window. (Zero means none stored — not necessarily no activity.)</div>
  }
  const H = 110, L = 34, bw = (W - L - 8) / rows.length, max = Math.max(...rows.map((r) => r[1]))
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H + 20}`} role="img" aria-label={`${caption}. Total ${total}, maximum ${max} per interval.`} className="w-full">
        <line x1={L} x2={W - 8} y1={H} y2={H} stroke="currentColor" className="text-charcoal-600" />
        <text x={L - 4} y={10} fontSize={10} textAnchor="end" className="fill-slate-500">{max}</text>
        <text x={L - 4} y={H} fontSize={10} textAnchor="end" className="fill-slate-500">0</text>
        {rows.map(([label, v], i) => {
          const h = (v / max) * (H - 12)
          return <rect key={label} x={L + i * bw + 0.5} y={H - h} width={Math.max(1, bw - 1)} height={h} className="fill-accent-500/80"><title>{`${label}: ${v} ${unit}`}</title></rect>
        })}
        <text x={L} y={H + 14} fontSize={10} className="fill-slate-500">{rows[0][0].slice(0, 16).replace('T', ' ')}</text>
        <text x={W - 8} y={H + 14} fontSize={10} textAnchor="end" className="fill-slate-500">{rows[rows.length - 1][0].slice(0, 16).replace('T', ' ')}</text>
      </svg>
      <figcaption className="mt-1 text-xs text-slate-500">{caption}. Total {total}.</figcaption>
    </figure>
  )
}

export function HBars({ title, unit, windowText, rows, onPick }: { title: string; unit: string; windowText: string; rows: [string, number][]; onPick?: (label: string) => void }) {
  const caption = `${title} · unit: ${unit} · ${windowText}`
  const max = Math.max(1, ...rows.map((r) => r[1]))
  if (rows.length === 0) return <div className="rounded-md border border-dashed border-charcoal-600 px-4 py-4 text-center text-xs text-slate-500">{title}: nothing recorded.</div>
  return (
    <figure aria-label={caption}>
      <ul className="space-y-1">
        {rows.map(([label, v]) => (
          <li key={label} className="flex items-center gap-2 text-xs">
            {onPick && label !== 'other' && label !== '(none)'
              ? <button type="button" onClick={() => onPick(label)} className="w-40 shrink-0 truncate text-left text-accent-400 hover:underline" title={`Filter to ${label}`}>{label}</button>
              : <span className="w-40 shrink-0 truncate text-slate-300" title={label}>{label}</span>}
            <span className="relative h-3 flex-1 rounded-sm bg-charcoal-800" aria-hidden="true"><span className="absolute inset-y-0 left-0 rounded-sm bg-accent-500/80" style={{ width: `${(v / max) * 100}%` }} /></span>
            <span className="w-14 text-right tabular-nums text-slate-200">{v}</span>
          </li>
        ))}
      </ul>
      <figcaption className="mt-1 text-xs text-slate-500">{caption}.</figcaption>
    </figure>
  )
}
