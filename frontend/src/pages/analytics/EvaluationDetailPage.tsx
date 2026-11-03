import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { ClassificationEvaluation } from '../../types/api'
import { ApiErrorView, MetricCard, SyntheticBadge } from '../../components/analytics/AnalyticsBits'
import { formatMetric } from '../../components/analytics/format'
import { Card, ErrorState, PageHeader, Spinner, StatusPill } from '../../components/ui/Primitives'
import { formatVersion } from '../../utils/version'

export function EvaluationDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const [run, setRun] = useState<ClassificationEvaluation | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (!runId) return
    api.analytics.evaluations.get(runId).then(setRun).catch(setError)
  }, [runId])

  if (error !== null) return <ApiErrorView error={error} />
  if (!run) return <Spinner />
  const c = run.results?.classification
  const p = run.results?.probability

  return (
    <div>
      <div className="mb-3 text-sm"><Link to="/analytics/evaluations" className="text-accent-400 hover:underline">&larr; Evaluation dashboard</Link></div>
      <PageHeader
        title={`Evaluation of ${run.dataset_name} ${formatVersion(run.dataset_version)}`}
        description={<span className="flex flex-wrap items-center gap-2"><StatusPill status={run.status} /><SyntheticBadge synthetic={run.is_synthetic} /></span>}
      />

      <div className={`mb-4 rounded-md border px-4 py-3 text-sm ${run.is_synthetic ? 'border-status-warning/30 bg-status-warning/10 text-status-warning' : 'border-charcoal-600 bg-charcoal-800/60 text-slate-300'}`}>
        {run.performance_claim}
      </div>

      <div className="mb-4 grid gap-4 md:grid-cols-3">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Model version</h2>
          <div className="font-mono text-xs text-slate-400">{run.model_record_id}</div>
          <div className="text-sm text-slate-300">v{run.model_version}</div>
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Dataset version</h2>
          <div className="text-sm text-slate-300">{run.dataset_name} {formatVersion(run.dataset_version)}</div>
          {run.dataset_reference && <div className="text-xs text-slate-500">{run.dataset_reference}</div>}
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Samples</h2>
          <div className="text-sm text-slate-300">{run.sample_count} submitted</div>
          <div className="text-xs text-slate-500">{run.excluded_missing_label} excluded for missing label</div>
          <div className="text-xs text-slate-500">Evaluated {new Date(run.evaluated_at).toLocaleString()}</div>
        </Card>
      </div>

      {run.status === 'failed' && <ErrorState message={run.error_message ?? 'This evaluation failed; no metrics were stored.'} />}
      {run.warnings.length > 0 && (
        <Card className="mb-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Warnings</h2>
          <ul className="list-disc space-y-1 pl-5 text-sm text-status-warning">{run.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </Card>
      )}

      {c && (
        <>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Classification metrics</h2>
          <div className="mb-4 grid gap-4 md:grid-cols-2">
            <MetricCard label="Accuracy" metric={c.accuracy} />
            <MetricCard label="Macro F1" metric={c.macro_f1} />
          </div>
          <div className="mb-4 grid gap-4 md:grid-cols-2">
            <Card>
              <h3 className="mb-2 text-sm font-semibold text-slate-200">Confusion matrix (rows: true, columns: predicted)</h3>
              <table className="text-sm">
                <thead>
                  <tr><th />{c.labels.map((l) => <th key={l} className="px-3 py-1 text-xs font-medium text-slate-500">{l}</th>)}</tr>
                </thead>
                <tbody>
                  {c.confusion_matrix.map((row, i) => (
                    <tr key={c.labels[i]}>
                      <th className="pr-3 text-right text-xs font-medium text-slate-500">{c.labels[i]}</th>
                      {row.map((n, j) => (
                        <td key={c.labels[j]} className={`px-3 py-1 text-center ${i === j ? 'bg-status-good/10 text-status-good' : n > 0 ? 'bg-status-critical/10 text-status-critical' : 'text-slate-500'}`}>{n}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card>
              <h3 className="mb-2 text-sm font-semibold text-slate-200">Per-class results</h3>
              <table className="w-full text-sm">
                <thead><tr className="text-left text-xs uppercase text-slate-500"><th>Class</th><th>Support</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead>
                <tbody>
                  {c.labels.map((l) => {
                    const m = c.per_class[l]
                    return (
                      <tr key={l} className="border-t border-charcoal-700/50">
                        <td className="py-1">{l}</td><td>{m.support}</td>
                        <td title={m.precision.reason ?? undefined}>{formatMetric(m.precision)}</td>
                        <td title={m.recall.reason ?? undefined}>{formatMetric(m.recall)}</td>
                        <td title={m.f1.reason ?? undefined}>{formatMetric(m.f1)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-slate-500">&ldquo;undefined&rdquo; means the metric cannot be computed (hover for the reason); it is not zero.</p>
            </Card>
          </div>
        </>
      )}

      {p && (
        <>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Probability-estimate metrics (positive class: {p.positive_label}; {p.scored_sample_count} scored)</h2>
          <div className="mb-4 grid gap-4 md:grid-cols-3">
            <MetricCard label="ROC-AUC" metric={p.roc_auc} />
            <MetricCard label="Brier score" metric={p.brier_score} />
            <MetricCard label="Log loss" metric={p.log_loss} />
          </div>
        </>
      )}

      <Card>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Evaluation configuration</h2>
        <pre className="overflow-x-auto rounded-md bg-navy-950 p-2 text-xs text-slate-400">{JSON.stringify(run.evaluation_config, null, 2)}</pre>
      </Card>
    </div>
  )
}
