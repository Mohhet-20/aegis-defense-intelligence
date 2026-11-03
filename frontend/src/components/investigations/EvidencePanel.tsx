import { useState } from 'react'
import { api } from '../../api/client'
import type { EvidenceDetail } from '../../types/workspace'
import { Button, Card, ErrorState, StatusPill } from '../ui/Primitives'
import { LoadState, Mono, Notice } from './InvestigationBits'
import { NotesPanel } from './NotesTab'
import { fmtTime, useLoad, RESULT_LABEL, errorText } from './useLoad'

const REVIEW = ['unreviewed', 'in_review', 'reviewed', 'disputed']

export function EvidencePanel({ investigationId, evidence, canWrite, canVerify, onChanged }: {
  investigationId: string; evidence: EvidenceDetail; canWrite: boolean; canVerify: boolean; onChanged: () => void
}) {
  const prov = useLoad(() => api.workspace.provenance(evidence.id), [evidence.id])
  const checks = useLoad(() => api.workspace.integrityChecks(evidence.id), [evidence.id])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function verify() {
    setBusy(true); setError(null)
    try { await api.workspace.verifyIntegrity(evidence.id); checks.reload() } catch (e) { setError(errorText(e, 'Verification failed.')) } finally { setBusy(false) }
  }
  async function review(status: string) {
    setError(null)
    try { await api.workspace.setEvidenceReview(evidence.id, status); onChanged(); prov.reload() } catch (e) { setError(errorText(e, 'Could not update review status.')) }
  }

  return (
    <div className="space-y-4">
      {error && <ErrorState message={error} />}
      <Card>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-100">{evidence.title}</h3>
          <StatusPill status={evidence.evidence_type} />
          <StatusPill status={evidence.review_status} />
          <span className="text-xs text-slate-500">access: {evidence.access_classification}</span>
          {evidence.superseded_by_evidence_id && <span className="text-xs text-status-warning">superseded by <Mono>{evidence.superseded_by_evidence_id}</Mono></span>}
        </div>
        {evidence.summary && <p className="mb-2 text-sm text-slate-300">{evidence.summary}</p>}
        <dl className="grid gap-2 text-sm md:grid-cols-2">
          <div><dt className="text-xs text-slate-500">Registered</dt><dd>{fmtTime(evidence.created_at)}</dd></div>
          <div><dt className="text-xs text-slate-500">Original capture / event time</dt><dd>{fmtTime(evidence.captured_at)}</dd></div>
          <div><dt className="text-xs text-slate-500">Reference</dt><dd>{evidence.external_reference_uri ? <Mono>{evidence.external_reference_uri}</Mono> : 'None'}</dd></div>
          <div><dt className="text-xs text-slate-500">Processing version</dt><dd>{evidence.processing_version ?? 'Unknown / not applicable'}</dd></div>
          <div className="md:col-span-2"><dt className="text-xs text-slate-500">Recorded hash ({evidence.integrity_hash_algorithm ?? 'algorithm unknown'})</dt><dd>{evidence.integrity_hash ? <Mono>{evidence.integrity_hash}</Mono> : 'None recorded'}</dd></div>
        </dl>
        {canWrite && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-400">
            Review status:
            {REVIEW.map((r) => <Button key={r} variant={evidence.review_status === r ? 'primary' : 'secondary'} onClick={() => review(r)}>{r}</Button>)}
          </div>
        )}
      </Card>

      <Card>
        <h4 className="mb-2 text-sm font-semibold text-slate-200">Provenance</h4>
        <LoadState loading={prov.loading} error={prov.error}>
          {prov.data && (
            <>
              <ol className="space-y-1 text-sm">
                {prov.data.chain.length === 0 && <li className="text-slate-500">No upstream records are recorded for this evidence.</li>}
                {prov.data.chain.map((n, i) => (
                  <li key={i} className="flex flex-wrap gap-2">
                    <span className="w-28 text-xs text-slate-500">{n.role.replace('_', ' ')}</span>
                    <span className={n.available ? 'text-slate-200' : 'text-status-warning'}>{n.label}</span>
                    <span className="text-xs text-slate-500">({n.record_type})</span>
                  </li>
                ))}
              </ol>
              <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-slate-400">{prov.data.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
            </>
          )}
        </LoadState>
      </Card>

      <Card>
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-sm font-semibold text-slate-200">Integrity checks</h4>
          {canVerify && <Button onClick={verify} disabled={busy}>{busy ? 'Verifying…' : 'Verify integrity now'}</Button>}
        </div>
        <Notice>Integrity compares stored bytes with the hash recorded earlier. It does not show the source was authentic or the content is true, and this history is an application audit trail, not a legal chain of custody.</Notice>
        <LoadState loading={checks.loading} error={checks.error}>
          {checks.data && checks.data.length === 0 ? <p className="text-sm text-slate-500">No checks have been run.</p> : (
            <ul className="space-y-1 text-sm">
              {(checks.data ?? []).map((c) => (
                <li key={c.id} className={c.result === 'mismatch' ? 'text-status-danger' : c.result === 'match' ? 'text-slate-200' : 'text-status-warning'}>
                  {fmtTime(c.created_at)} -- {RESULT_LABEL[c.result] ?? c.result}
                </li>
              ))}
            </ul>
          )}
        </LoadState>
      </Card>

      <Card>
        <h4 className="mb-2 text-sm font-semibold text-slate-200">Annotations on this evidence</h4>
        <NotesPanel investigationId={investigationId} evidenceId={evidence.id} canWrite={canWrite} />
      </Card>
    </div>
  )
}
