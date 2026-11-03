import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { Explanation, ModelOutputType } from '../../types/api'
import { ApiErrorView } from './AnalyticsBits'
import { Card, Spinner } from '../ui/Primitives'

function renderValue(v: unknown): string {
  if (v === undefined || v === null) return '--'
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

export function ExplanationPanel({ outputType, outputId }: { outputType: ModelOutputType; outputId: string }) {
  const [method, setMethod] = useState<string | undefined>(undefined)
  const [data, setData] = useState<Explanation | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    setData(null)
    setError(null)
    api.analytics.outputs.explanation(outputType, outputId, method).then(setData).catch(setError)
  }, [outputType, outputId, method])

  if (error !== null) return <ApiErrorView error={error} />
  if (!data) return <Spinner />

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-200">Explanation</h2>
        <select
          className="rounded-md border border-charcoal-600 bg-charcoal-900 px-2 py-1 text-xs text-slate-200"
          value={method ?? ''}
          onChange={(e) => setMethod(e.target.value || undefined)}
          aria-label="Explanation method"
        >
          <option value="">Best available method</option>
          {data.available_methods.map((m) => (
            <option key={m.method_key} value={m.method_key}>{m.label}{m.supported ? '' : ' (not supported)'}</option>
          ))}
        </select>
      </div>

      {data.supported ? (
        <>
          <div className="mb-2 text-xs text-slate-400">
            {data.label} &middot; <span className="uppercase">{data.explanation_kind?.replace(/_/g, ' ')}</span>
          </div>
          <table className="mb-3 w-full text-sm">
            <tbody>
              {data.items.map((i) => (
                <tr key={i.name} className="border-t border-charcoal-700/50">
                  <td className="py-1.5 pr-3 text-slate-300">{i.name}</td>
                  <td className="py-1.5 pr-3 font-mono text-xs text-slate-200">{renderValue(i.value ?? i.detail)}</td>
                  <td className="py-1.5 text-xs text-slate-500">
                    {i.contribution !== undefined && `contribution ${i.contribution} (weight ${i.weight})`}
                    {i.contribution === undefined && typeof i.detail === 'string' ? i.detail : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.method_detail && <p className="mb-2 text-xs text-slate-400">{data.method_detail}</p>}
          {data.interpretation_note && (
            <p className="rounded-md border border-charcoal-600 bg-navy-950 px-3 py-2 text-xs text-slate-400">{data.interpretation_note}</p>
          )}
        </>
      ) : (
        <div className="rounded-md border border-status-warning/30 bg-status-warning/10 px-3 py-2 text-sm text-status-warning">
          No explanation available: {data.limitation}
        </div>
      )}

      <details className="mt-3 text-xs text-slate-500">
        <summary className="cursor-pointer">Method availability for this output</summary>
        <ul className="mt-2 space-y-1">
          {data.available_methods.map((m) => (
            <li key={m.method_key}>
              <span className={m.supported ? 'text-status-good' : 'text-slate-400'}>{m.supported ? '✓' : '✗'} {m.label}</span>
              {m.limitation && <span> &mdash; {m.limitation}</span>}
            </li>
          ))}
        </ul>
      </details>
    </Card>
  )
}
