import { useEffect, useState } from 'react'
import { governanceApi } from '../api/governance'
import type { SecurityConfigReport } from '../types/governance'
import { Card, ErrorState, PageHeader, Spinner } from '../components/ui/Primitives'

const SEV: Record<string, string> = {
  critical: 'bg-status-critical/20 text-status-critical', high: 'bg-status-critical/10 text-status-critical',
  medium: 'bg-yellow-500/15 text-yellow-300', low: 'bg-charcoal-700 text-slate-300', info: 'bg-charcoal-700 text-slate-400',
}

/** Read-only security configuration. Secret values are never returned by the backend. */
export function SecurityConfigPage() {
  const [data, setData] = useState<SecurityConfigReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { governanceApi.securityConfig().then(setData).catch((e) => setError(e.message)) }, [])
  return (
    <div>
      <PageHeader
        title="Security Configuration"
        description="Read-only view of security-relevant settings and findings derived from them. Secret values are never displayed. A short findings list is not proof of security — see the known-risks document."
      />
      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && (
        <div className="space-y-5">
          <Card>
            <div className="mb-2 text-sm text-slate-300">Environment: <span className="font-mono">{data.environment}</span></div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Findings ({data.findings.length})</h3>
            {data.findings.length === 0 && <div className="text-sm text-slate-500">No configuration findings.</div>}
            <ul className="space-y-2">
              {data.findings.map((f) => (
                <li key={f.id} className="rounded-sm border border-charcoal-600 p-3">
                  <div className="flex items-center gap-2"><span className={`rounded-sm px-1.5 py-0.5 text-[10px] font-semibold uppercase ${SEV[f.severity]}`}>{f.severity}</span><span className="text-sm text-slate-100">{f.title}</span></div>
                  {f.detail && <div className="mt-1 text-xs text-slate-400">{f.detail}</div>}
                  <div className="mt-1 text-xs text-slate-500">Fix: {f.recommendation}</div>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Effective settings</h3>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs md:grid-cols-2">
              {Object.entries(data.settings).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 border-b border-charcoal-700/50 py-1"><dt className="text-slate-500">{k}</dt><dd className="font-mono text-slate-200">{String(v)}</dd></div>
              ))}
            </dl>
            <h3 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Secrets (configured? — values hidden)</h3>
            <ul className="text-xs text-slate-300">{Object.entries(data.secrets_configured).map(([k, v]) => <li key={k}>{k}: {v ? 'yes' : 'no'}</li>)}</ul>
          </Card>
          <Card>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Not implemented</h3>
            <ul className="list-disc pl-5 text-xs text-slate-300">{data.not_implemented.map((n) => <li key={n}>{n}</li>)}</ul>
          </Card>
        </div>
      )}
    </div>
  )
}
