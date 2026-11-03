import { useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import type { SearchPage } from '../../types/workspace'
import { Button, Card, EmptyState, Field, StatusPill, inputClass } from '../ui/Primitives'
import { Pagination } from '../tables/DataTable'
import { LoadState, Mono, Notice } from './InvestigationBits'
import { fmtTime, useLoad } from './useLoad'

export function SearchTab({ investigationId }: { investigationId: string }) {
  const [q, setQ] = useState('')
  const [quality, setQuality] = useState('')
  const [type, setType] = useState('')
  const [applied, setApplied] = useState({ q: '', quality: '', type: '' })
  const [page, setPage] = useState(1)
  const results = useLoad<SearchPage>(
    () => api.workspace.search(investigationId, { q: applied.q || undefined, data_quality: applied.quality || undefined, record_type: applied.type ? [applied.type] : undefined, page }),
    [investigationId, applied, page],
  )
  const rels = useLoad(() => api.workspace.relationships(investigationId), [investigationId])

  function submit(e: FormEvent) {
    e.preventDefault()
    setPage(1)
    setApplied({ q, quality, type })
  }

  return (
    <div className="space-y-4">
      <Card>
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-4">
          <Field label="Text"><input className={inputClass} value={q} onChange={(e) => setQ(e.target.value)} maxLength={200} /></Field>
          <Field label="Record type">
            <select className={inputClass} value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">All</option>
              {['event', 'observation', 'media_asset', 'assessment', 'evidence', 'detection_result', 'track', 'data_source', 'sensor', 'note'].map((t) => <option key={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Data quality">
            <select className={inputClass} value={quality} onChange={(e) => setQuality(e.target.value)}>
              <option value="">Any</option><option value="clean">clean</option><option value="flagged">flagged</option><option value="unknown">unknown</option>
            </select>
          </Field>
          <div className="flex items-end"><Button type="submit">Search</Button></div>
        </form>
      </Card>
      <LoadState loading={results.loading} error={results.error}>
        {results.data && <Notice>{results.data.note}</Notice>}
        {results.data && results.data.items.length === 0 ? <EmptyState message="No linked records match." /> : (
          <Card>
            <ul className="divide-y divide-charcoal-700 text-sm">
              {(results.data?.items ?? []).map((r) => (
                <li key={`${r.record_type}:${r.record_id}`} className="py-2">
                  <div className="flex flex-wrap items-center gap-2"><StatusPill status={r.record_type} /><span className="text-slate-200">{r.title}</span>{r.review_status && <StatusPill status={r.review_status} />}<span className="text-xs text-slate-500">quality: {r.data_quality}</span></div>
                  <div className="text-xs text-slate-500">{r.primary_time_kind ?? 'time'}: {fmtTime(r.primary_time)} · <Mono>{r.record_id}</Mono></div>
                  {r.summary && <div className="text-xs text-slate-400">{r.summary}</div>}
                </li>
              ))}
            </ul>
            {results.data && <Pagination page={results.data.page} pageSize={results.data.page_size} total={results.data.total} onPageChange={setPage} />}
          </Card>
        )}
      </LoadState>
      <Card>
        <h3 className="mb-2 text-sm font-semibold text-slate-200">Relationships between linked records</h3>
        <LoadState loading={rels.loading} error={rels.error}>
          {rels.data && <Notice>{rels.data.notice}</Notice>}
          {rels.data && rels.data.items.length === 0 ? <p className="text-sm text-slate-500">No recorded relationships involve these records.</p> : (
            <ul className="space-y-2 text-sm">
              {(rels.data?.items ?? []).map((r) => (
                <li key={r.relationship_id} className="rounded-sm border border-charcoal-700 p-2">
                  <div className="flex flex-wrap items-center gap-2"><span className="text-slate-200">{r.relationship_type}</span><StatusPill status={r.review_status} /><span className="text-xs text-slate-400">{r.origin_label}</span>{!r.is_confirmed && <span className="text-xs text-status-warning">not confirmed</span>}</div>
                  <div className="text-xs text-slate-500"><Mono>{r.source.record_id}</Mono> → <Mono>{r.target.record_id}</Mono></div>
                  <div className="text-xs text-slate-400">Why: {r.explanation}</div>
                </li>
              ))}
            </ul>
          )}
        </LoadState>
      </Card>
    </div>
  )
}
