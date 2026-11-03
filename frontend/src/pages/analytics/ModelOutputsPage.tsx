import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { ModelOutput, ModelOutputPage, ModelOutputType } from '../../types/api'
import { ApiErrorView } from '../../components/analytics/AnalyticsBits'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import { EmptyState, PageHeader, Spinner, StatusPill, Tabs } from '../../components/ui/Primitives'
import { formatVersion } from '../../utils/version'

export function ModelOutputsPage() {
  const navigate = useNavigate()
  const [type, setType] = useState<ModelOutputType>('detection_result')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<ModelOutputPage | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    setData(null)
    api.analytics.outputs
      .list({ output_type: type, page, page_size: 20 })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch(setError)
  }, [type, page])

  return (
    <div>
      <PageHeader
        title="Model Outputs"
        description="Detection results and risk-assessment scores in one shared schema. Open an output to inspect its explanation and data-quality limitations. Confidence is shown only when the model provided one."
      />
      <Tabs
        tabs={[
          { key: 'detection_result', label: 'Detections' },
          { key: 'risk_assessment', label: 'Risk assessments' },
        ]}
        active={type}
        onChange={(k) => {
          setType(k as ModelOutputType)
          setPage(1)
        }}
      />
      <div className="mt-4">
        {error !== null && <ApiErrorView error={error} />}
        {error === null && data === null && <Spinner />}
        {data && data.skipped_invalid > 0 && (
          <div className="mb-3 rounded-md border border-status-warning/30 bg-status-warning/10 px-3 py-2 text-xs text-status-warning">
            {data.skipped_invalid} record(s) on this page failed schema validation and are not shown.
          </div>
        )}
        {data && data.items.length === 0 && <EmptyState message="No outputs of this type exist yet." />}
        {data && data.items.length > 0 && (
          <>
            <DataTable
              rows={data.items.map((o) => ({ ...o, id: o.output_id }))}
              onRowClick={(o: ModelOutput) => navigate(`/analytics/outputs/${o.output_type}/${o.output_id}`)}
              columns={[
                { header: 'Prediction', render: (o) => (o.output_type === 'detection_result' ? String(o.prediction.label) : `score ${String(o.prediction.value)}`) },
                { header: 'Model', render: (o) => `${o.model.name} ${formatVersion(o.model.version)}` },
                { header: 'Confidence', render: (o) => (o.confidence_provided && o.confidence !== null ? o.confidence.toFixed(2) : <span className="text-slate-500">not provided</span>) },
                { header: 'Status', render: (o) => <StatusPill status={o.execution_status} /> },
                { header: 'Review', render: (o) => (o.review_status ? <StatusPill status={o.review_status} /> : '--') },
                { header: 'Quality flags', render: (o) => o.data_quality.filter((q) => q.severity !== 'info').length || '--' },
                { header: 'Processed', render: (o) => new Date(o.processed_at).toLocaleString() },
              ]}
            />
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
          </>
        )}
      </div>
    </div>
  )
}
