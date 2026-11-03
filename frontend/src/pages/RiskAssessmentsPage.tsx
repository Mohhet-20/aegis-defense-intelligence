import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Page, RiskAssessment } from '../types/api'
import { useAuth } from '../context/auth'
import { DataTable } from '../components/tables/DataTable'
import { Button, Card, EmptyState, ErrorState, PageHeader, Spinner, StatusPill } from '../components/ui/Primitives'

export function RiskAssessmentsPage() {
  const { user } = useAuth()
  const [data, setData] = useState<Page<RiskAssessment> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const canReview = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  function load() {
    api.riskAssessments
      .list()
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [])

  async function review(id: string, status: 'confirmed' | 'dismissed') {
    setActionError(null)
    try {
      await api.riskAssessments.review(id, status)
      load()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not record review.')
    }
  }

  return (
    <div>
      <PageHeader
        title="Risk Assessments"
        description="A model's score is not a verified fact -- every row starts pending and only a human review changes that."
      />

      {actionError && <ErrorState message={actionError} />}
      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && data.items.length === 0 && <EmptyState message="No risk assessments recorded yet." />}
      {data && data.items.length > 0 && (
        <DataTable
          rows={data.items}
          columns={[
            { header: 'Subject', render: (r) => <span className="font-mono text-xs">{r.subject_type}:{r.subject_id.slice(0, 8)}</span> },
            { header: 'Method', render: (r) => r.method },
            { header: 'Score', render: (r) => `${r.score.toFixed(0)} / 100` },
            { header: 'Confidence', render: (r) => (r.confidence !== null ? r.confidence.toFixed(2) : '--') },
            { header: 'Review', render: (r) => <StatusPill status={r.human_review_status} /> },
            {
              header: 'Action',
              render: (r) =>
                canReview && r.human_review_status === 'pending' ? (
                  <div className="flex gap-2">
                    <Button variant="secondary" onClick={() => review(r.id, 'confirmed')}>
                      Confirm
                    </Button>
                    <Button variant="secondary" onClick={() => review(r.id, 'dismissed')}>
                      Dismiss
                    </Button>
                  </div>
                ) : (
                  <span className="text-slate-500">--</span>
                ),
            },
          ]}
        />
      )}

      {data && data.items.length > 0 && (
        <Card className="mt-5">
          <h2 className="mb-1 text-sm font-semibold text-slate-200">Explanation (uncalibrated score)</h2>
          <p className="text-xs text-slate-500">{data.items[0].score_scale}</p>
        </Card>
      )}
    </div>
  )
}
