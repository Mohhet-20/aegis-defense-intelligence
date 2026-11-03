import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { ModelOutput, ModelOutputType } from '../../types/api'
import { ApiErrorView, DataQualityList } from '../../components/analytics/AnalyticsBits'
import { ExplanationPanel } from '../../components/analytics/ExplanationPanel'
import { Card, PageHeader, Spinner, StatusPill } from '../../components/ui/Primitives'

function recordLink(type: string, id: string): string | null {
  if (type === 'inference_job') return `/cv/jobs/${id}`
  if (type === 'evidence') return '/fusion/evidence'
  if (type === 'media_asset') return '/cv/media'
  return null
}

export function ModelOutputDetailPage() {
  const { outputType, outputId } = useParams<{ outputType: ModelOutputType; outputId: string }>()
  const [output, setOutput] = useState<ModelOutput | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (!outputType || !outputId) return
    api.analytics.outputs.get(outputType, outputId).then(setOutput).catch(setError)
  }, [outputType, outputId])

  if (error !== null) return <ApiErrorView error={error} />
  if (!output) return <Spinner />
  // A record can be both an input and a supporting record (e.g. the media asset); list it once.
  const linkedRecords = [...output.input_refs, ...output.supporting_records].filter(
    (r, i, all) => all.findIndex((o) => o.type === r.type && o.id === r.id) === i,
  )

  return (
    <div>
      <div className="mb-3 text-sm"><Link to="/analytics/outputs" className="text-accent-400 hover:underline">&larr; Model outputs</Link></div>
      <PageHeader
        title={output.output_type === 'detection_result' ? `Detection: ${String(output.prediction.label)}` : `Risk score: ${String(output.prediction.value)}`}
        description={<span className="flex flex-wrap items-center gap-2"><StatusPill status={output.execution_status} />{output.review_status && <StatusPill status={output.review_status} />}</span>}
      />

      <div className="mb-4 grid gap-4 md:grid-cols-3">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Model</h2>
          <div className="text-sm text-slate-300">{output.model.name}</div>
          <div className="text-xs text-slate-500">version {output.model.version}{output.model.adapter_key ? ` · adapter ${output.model.adapter_key}` : ''}</div>
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Confidence</h2>
          {output.confidence_provided && output.confidence !== null ? (
            <div className="text-2xl font-semibold text-slate-100">{output.confidence.toFixed(2)}</div>
          ) : (
            <div className="text-sm text-slate-400">Not provided by the model</div>
          )}
          {output.confidence_note && <p className="mt-1 text-xs text-slate-500">{output.confidence_note}</p>}
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Processed</h2>
          <div className="text-sm text-slate-300">{new Date(output.processed_at).toLocaleString()}</div>
          <div className="text-xs text-slate-500">schema {output.schema_version}</div>
        </Card>
      </div>

      <div className="mb-4 grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Data-quality limitations</h2>
          <DataQualityList items={output.data_quality} />
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Supporting records</h2>
          {linkedRecords.length === 0 && <p className="text-sm text-slate-500">None linked.</p>}
          <ul className="space-y-1 text-sm">
            {linkedRecords.map((r) => {
              const to = recordLink(r.type, r.id)
              return (
                <li key={`${r.type}-${r.id}`} className="flex gap-2">
                  <span className="w-28 shrink-0 text-xs uppercase text-slate-500">{r.type.replace(/_/g, ' ')}</span>
                  {to ? <Link to={to} className="font-mono text-xs text-accent-400 hover:underline">{r.id}</Link> : <span className="font-mono text-xs text-slate-400">{r.id}</span>}
                </li>
              )
            })}
          </ul>
        </Card>
      </div>

      <div className="mb-4">
        <ExplanationPanel outputType={output.output_type} outputId={output.output_id} />
      </div>

      <Card>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Recorded features</h2>
        <pre className="overflow-x-auto rounded-md bg-navy-950 p-2 text-xs text-slate-400">{JSON.stringify(output.features, null, 2)}</pre>
      </Card>
    </div>
  )
}
