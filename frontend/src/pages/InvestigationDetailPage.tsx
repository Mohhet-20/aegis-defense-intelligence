import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../context/auth'
import { LoadState } from '../components/investigations/InvestigationBits'
import { CopilotTab } from '../components/investigations/CopilotTab'
import { EvidenceTab } from '../components/investigations/EvidenceTab'
import { NotesPanel } from '../components/investigations/NotesTab'
import { OverviewTab } from '../components/investigations/OverviewTab'
import { SearchTab } from '../components/investigations/SearchTab'
import { TimelineTab } from '../components/investigations/TimelineTab'
import { useLoad } from '../components/investigations/useLoad'
import { PageHeader, Tabs } from '../components/ui/Primitives'

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'evidence', label: 'Evidence' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'notes', label: 'Notes & review' },
  { key: 'search', label: 'Search & relationships' },
  { key: 'copilot', label: 'Copilot' },
]

export function InvestigationDetailPage() {
  const { investigationId = '' } = useParams<{ investigationId: string }>()
  const { user } = useAuth()
  const [tab, setTab] = useState('overview')
  const inv = useLoad(() => api.workspace.get(investigationId), [investigationId])
  const canManage = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'
  const canVerify = canManage

  return (
    <div>
      <LoadState loading={inv.loading && !inv.data} error={inv.error}>
        {inv.data && (
          <>
            <PageHeader
              title={inv.data.title}
              description={<><Link to="/investigations" className="text-accent-400 hover:underline">Investigations</Link> / {inv.data.id}</>}
            />
            <Tabs tabs={TABS} active={tab} onChange={setTab} />
            {tab === 'overview' && <OverviewTab inv={inv.data} canWrite={canManage} onChanged={inv.reload} />}
            {tab === 'evidence' && <EvidenceTab investigationId={inv.data.id} canWrite={canManage} canVerify={canVerify} readOnly={inv.data.status === 'archived'} />}
            {tab === 'timeline' && <TimelineTab investigationId={inv.data.id} />}
            {tab === 'notes' && <NotesPanel investigationId={inv.data.id} canWrite={canManage} readOnly={inv.data.status === 'archived'} />}
            {tab === 'search' && <SearchTab investigationId={inv.data.id} />}
            {tab === 'copilot' && <CopilotTab investigationId={inv.data.id} canWrite={canManage} readOnly={inv.data.status === 'archived'} />}
          </>
        )}
      </LoadState>
    </div>
  )
}
