import { useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import type { EvidenceDetail } from '../../types/workspace'
import { Button, Card, EmptyState, ErrorState, Field, StatusPill, inputClass } from '../ui/Primitives'
import { EvidencePanel } from './EvidencePanel'
import { LoadState, Notice } from './InvestigationBits'
import { useLoad, errorText } from './useLoad'

const REF_TYPES = [
  { v: 'media_asset', l: 'Uploaded media (by id)', ref: 'record_id' },
  { v: 'detection', l: 'Detection (by id)', ref: 'record_id' },
  { v: 'track', l: 'Track (by id)', ref: 'record_id' },
  { v: 'data_source', l: 'Data source (by id)', ref: 'record_id' },
  { v: 'assessment_version', l: 'Assessment version (by id)', ref: 'record_id' },
  { v: 'observation', l: 'Event (by id)', ref: 'event_id' },
  { v: 'sensor_observation', l: 'Sensor observation (by id)', ref: 'observation_id' },
  { v: 'analyst_note', l: 'Analyst note (text)', ref: 'content' },
  { v: 'report', l: 'Report text', ref: 'content' },
  { v: 'document', l: 'External document (URI)', ref: 'external_reference_uri' },
] as const

export function EvidenceTab({ investigationId, canWrite, canVerify, readOnly }: { investigationId: string; canWrite: boolean; canVerify: boolean; readOnly: boolean }) {
  const list = useLoad(() => api.workspace.evidence(investigationId), [investigationId])
  const [selected, setSelected] = useState<EvidenceDetail | null>(null)
  const [type, setType] = useState<(typeof REF_TYPES)[number]['v']>('media_asset')
  const [title, setTitle] = useState('')
  const [ref, setRef] = useState('')
  const [claimedHash, setClaimedHash] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const refKind = REF_TYPES.find((t) => t.v === type)?.ref ?? 'record_id'

  async function register(e: FormEvent) {
    e.preventDefault()
    setError(null); setInfo(null)
    try {
      const res = await api.workspace.registerEvidence(investigationId, {
        evidence_type: type, title, [refKind]: ref, ...(type === 'document' && claimedHash ? { claimed_hash: claimedHash } : {}),
      })
      setInfo(res.reused_existing ? 'Existing evidence for this record was reused and linked (nothing was copied).' : 'Evidence registered.')
      setTitle(''); setRef(''); setClaimedHash('')
      list.reload()
      setSelected(res.evidence)
    } catch (err) { setError(errorText(err, 'Could not register evidence.')) }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-3 lg:col-span-1">
        {canWrite && !readOnly && (
          <Card>
            <h3 className="mb-2 text-sm font-semibold text-slate-200">Register evidence</h3>
            <form onSubmit={register} className="space-y-3">
              <Field label="Kind"><select className={inputClass} value={type} onChange={(e) => setType(e.target.value as typeof type)}>{REF_TYPES.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}</select></Field>
              <Field label="Title"><input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={300} /></Field>
              <Field label={refKind === 'content' ? 'Text' : refKind === 'external_reference_uri' ? 'URI' : 'Record id'}>
                {refKind === 'content' ? <textarea className={inputClass} rows={3} value={ref} onChange={(e) => setRef(e.target.value)} required /> : <input className={inputClass} value={ref} onChange={(e) => setRef(e.target.value)} required />}
              </Field>
              {type === 'document' && <Field label="Hash you were given (optional, unverified)"><input className={inputClass} value={claimedHash} onChange={(e) => setClaimedHash(e.target.value)} /></Field>}
              {error && <ErrorState message={error} />}
              {info && <p className="text-xs text-slate-400">{info}</p>}
              <Button type="submit">Register and link</Button>
            </form>
            <p className="mt-2 text-xs text-slate-500">Evidence points to existing records; files are never copied. Unknown capture times stay unknown.</p>
          </Card>
        )}
        <LoadState loading={list.loading} error={list.error}>
          {list.data && list.data.length === 0 ? <EmptyState message="No evidence registered for this investigation." /> : (
            <ul className="space-y-2">
              {(list.data ?? []).map((ev) => (
                <li key={ev.id}>
                  <button type="button" onClick={() => setSelected(ev)} className={`w-full rounded-md border px-3 py-2 text-left text-sm ${selected?.id === ev.id ? 'border-accent-500 bg-charcoal-800' : 'border-charcoal-700 hover:bg-charcoal-800/60'}`}>
                    <div className="text-slate-200">{ev.title}</div>
                    <div className="mt-1 flex gap-2"><StatusPill status={ev.evidence_type} /><StatusPill status={ev.review_status} />{ev.superseded_by_evidence_id && <span className="text-xs text-status-warning">superseded</span>}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </LoadState>
      </div>
      <div className="lg:col-span-2">
        {selected ? <EvidencePanel key={selected.id} investigationId={investigationId} evidence={selected} canWrite={canWrite && !readOnly} canVerify={canVerify} onChanged={list.reload} /> : (
          <Notice>Select evidence to see its metadata, provenance, integrity checks and annotations.</Notice>
        )}
      </div>
    </div>
  )
}
