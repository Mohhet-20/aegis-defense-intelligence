import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { Evidence, Page } from '../../types/api'
import { DataTable, Pagination } from '../../components/tables/DataTable'
import { EmptyState, ErrorState, PageHeader, Spinner } from '../../components/ui/Primitives'

export function CVEvidenceLinksPage() {
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<Evidence> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.evidence
      .list({ page, page_size: 20, evidence_type: 'media_reference' })
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }, [page])

  return (
    <div>
      <PageHeader
        title="Evidence Integration"
        description="Every row here is a media_reference Evidence item created by promoting a CONFIRMED detection -- never an unreviewed one. This is the required lineage's final step: Media asset → Inference job → Model → Detection result → Evidence → Analyst review."
      />

      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && (
        <EmptyState message="No detections have been promoted to Evidence yet -- confirm a detection in the Image Detection Workspace, then promote it." />
      )}
      {data && data.items.length > 0 && (
        <>
          <DataTable
            rows={data.items}
            columns={[
              { header: 'Title', render: (e) => e.title },
              { header: 'Summary', render: (e) => e.summary ?? '--' },
              { header: 'Detection', render: (e) => (e.detection_result_id ? <span className="font-mono text-xs">{e.detection_result_id.slice(0, 8)}</span> : '--') },
              { header: 'Reference', render: (e) => <span className="font-mono text-xs">{e.external_reference_uri}</span> },
              {
                header: 'Fusion links',
                render: () => (
                  <Link to="/fusion/evidence" className="text-accent-400 hover:underline">
                    view in evidence library
                  </Link>
                ),
              },
              { header: 'Created', render: (e) => new Date(e.created_at).toLocaleString() },
            ]}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  )
}
