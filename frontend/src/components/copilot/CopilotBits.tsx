import { useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { copilotApi } from '../../api/copilot'
import type { Answer, Citation, Claim, SearchHit, SearchResponse } from '../../types/copilot'
import { RECORD_TYPES, hitKey } from '../../types/copilot'
import { Button, Card, EmptyState, Field, StatusPill, inputClass } from '../ui/Primitives'
import { Pagination } from '../tables/DataTable'
import { LoadState, Mono, Notice } from '../investigations/InvestigationBits'
import { fmtTime, useLoad } from '../investigations/useLoad'

const KIND_LABEL: Record<Claim['kind'], { label: string; cls: string; hint: string }> = {
  source_statement: { label: 'Source text', cls: 'border-accent-500/30 bg-accent-500/10 text-accent-400', hint: 'Verbatim text from a record' },
  record_summary: { label: 'Record summary', cls: 'border-slate-500/30 bg-slate-500/10 text-slate-300', hint: 'Assembled by the application from stored fields; not written by a model' },
  generated_summary: { label: 'Model-written', cls: 'border-status-warning/40 bg-status-warning/10 text-status-warning', hint: 'Written by a language model; check it against the cited source' },
  system_note: { label: 'Notice', cls: 'border-charcoal-500 bg-charcoal-800 text-slate-300', hint: 'Limitation or notice from the application' },
}

const MODE_LABEL: Record<Answer['mode'], string> = {
  extractive: 'Source excerpts only (no model-written text)',
  generative: 'Contains model-written text (marked)',
  deterministic: 'Assembled from records (no model)',
}

function citeNumber(a: Answer, id: string): number {
  return a.citations.findIndex((c) => c.id === id) + 1
}

function CitationStatus({ c }: { c: Citation }) {
  const tone: Record<string, string> = {
    verified: 'text-status-success', source_changed: 'text-status-warning', unavailable: 'text-status-critical',
    access_revoked: 'text-status-critical', unverified: 'text-status-warning',
  }
  return <span className={`text-xs ${tone[c.status] ?? 'text-slate-400'}`}>{c.status.replace(/_/g, ' ')}</span>
}

export function CitationChips({ answer, ids }: { answer: Answer; ids: string[] }) {
  if (ids.length === 0) return <span className="text-xs text-slate-500">no citation</span>
  return (
    <span className="inline-flex flex-wrap gap-1">
      {ids.map((id) => {
        const n = citeNumber(answer, id)
        const c = answer.citations.find((x) => x.id === id)
        return (
          <a key={id} href={`#cit-${id}`} title={c ? `${c.title ?? c.record_id} (${c.status})` : 'unknown citation'}
            className={`rounded-sm border px-1.5 text-xs ${c && c.status === 'verified' ? 'border-charcoal-500 text-accent-400' : 'border-status-warning/40 text-status-warning'}`}>
            [{n || '?'}]
          </a>
        )
      })}
    </span>
  )
}

function CitationCard({ c, n }: { c: Citation; n: number }) {
  const readable = c.status === 'verified' || c.status === 'source_changed'
  return (
    <li id={`cit-${c.id}`} className="rounded-sm border border-charcoal-700 p-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-500">[{n}]</span>
        <StatusPill status={c.record_type} />
        <span className="text-slate-200">{c.title ?? (readable ? c.record_id : 'Source withheld')}</span>
        <CitationStatus c={c} />
        {c.link && readable && <Link to={c.link} className="text-xs text-accent-400 hover:underline">open record</Link>}
      </div>
      <div className="text-xs text-slate-500">
        {c.source_time ? `Record time: ${fmtTime(c.source_time)}` : 'No record time'}
        {c.document_version != null && ` · indexed version ${c.document_version}`}
        {c.section && ` · section "${c.section}"`} · <Mono>{c.record_id}</Mono>
      </div>
      {c.quote && <blockquote className="mt-1 whitespace-pre-wrap border-l-2 border-charcoal-600 pl-2 text-xs text-slate-300">{c.quote}</blockquote>}
      {c.status_note && <div className="mt-1 text-xs text-status-warning">{c.status_note}</div>}
    </li>
  )
}

function ConflictView({ answer }: { answer: Answer }) {
  if (answer.conflicts.length === 0) return null
  const pick = (ids: string[]) => ids.map((i) => answer.citations.find((c) => c.id === i)).filter((c): c is Citation => !!c)
  return (
    <div className="mb-3">
      <h4 className="mb-1 text-sm font-semibold text-status-warning">Conflicting information (not resolved)</h4>
      <ul className="space-y-2">
        {answer.conflicts.map((cf, i) => (
          <li key={i} className="rounded-sm border border-status-warning/30 bg-status-warning/5 p-2 text-sm">
            <div className="mb-2 text-slate-200">{cf.description}</div>
            <div className="grid gap-2 md:grid-cols-2">
              {[pick(cf.left_citation_ids), pick(cf.right_citation_ids)].map((side, k) => (
                <div key={k} className="rounded-sm border border-charcoal-700 bg-charcoal-900 p-2 text-xs">
                  <div className="mb-1 text-slate-500">{k === 0 ? 'Side A' : 'Side B'}</div>
                  {side.length === 0 ? <span className="text-slate-500">Source withheld</span> : side.map((c) => (
                    <div key={c.id ?? c.record_id}>
                      <div className="text-slate-200">{c.title ?? c.record_id} <span className="text-slate-500">({c.record_type}, {c.source_time ? fmtTime(c.source_time) : 'no time'})</span></div>
                      {c.quote && <div className="mt-1 whitespace-pre-wrap text-slate-300">{c.quote}</div>}
                    </div>
                  ))}
                </div>
              ))}
            </div>
            <div className="mt-1 text-xs text-slate-400">{cf.basis}</div>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function AnswerView({ answer, onFollowup }: { answer: Answer; onFollowup?: (q: string) => void }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-sm border border-charcoal-600 px-2 py-0.5 text-slate-300">{MODE_LABEL[answer.mode]}</span>
        <StatusPill status={answer.status} />
        <span className="text-slate-500">{fmtTime(answer.generated_at)}</span>
        {answer.reverified_at && <span className="text-slate-500">citations re-checked {fmtTime(answer.reverified_at)}</span>}
      </div>
      {answer.generation.notice && <Notice tone="warn">{answer.generation.notice}</Notice>}
      {(answer.status === 'no_relevant_records' || answer.status === 'insufficient') && (
        <Notice tone="warn">The records you can access do not answer this question. Nothing was inferred.</Notice>
      )}
      <ul className="space-y-2">
        {answer.claims.map((c) => {
          const k = KIND_LABEL[c.kind]
          return (
            <li key={c.id} className="rounded-sm border border-charcoal-700 p-2 text-sm">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span title={k.hint} className={`rounded-full border px-2 py-0.5 text-xs ${k.cls}`}>{k.label}</span>
                {c.support === 'weak_overlap' && <span className="text-xs text-status-warning">little wording shared with its source</span>}
                {c.support === 'unverified' && <span className="text-xs text-status-warning">cited source not retrieved</span>}
                {c.support === 'none' && c.kind === 'generated_summary' && <span className="text-xs text-status-warning">no source</span>}
                {c.source_changed && <span className="text-xs text-status-warning">source changed since this answer</span>}
                {c.withheld && <span className="text-xs text-status-critical">withheld</span>}
              </div>
              <div className={`whitespace-pre-wrap ${c.kind === 'source_statement' ? 'border-l-2 border-accent-500/50 pl-2 text-slate-300' : 'text-slate-200'}`}>{c.text}</div>
              {c.kind !== 'system_note' && <div className="mt-1"><CitationChips answer={answer} ids={c.citation_ids} /></div>}
            </li>
          )
        })}
      </ul>
      <ConflictView answer={answer} />
      {answer.side_by_side && answer.side_by_side.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-semibold text-slate-200">Side-by-side source excerpts</h4>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {answer.side_by_side.map((s) => (
              <div key={s.citation_id} className="rounded-sm border border-charcoal-700 p-2 text-xs">
                <div className="mb-1 flex flex-wrap items-center gap-2"><StatusPill status={s.record_type} /><span className="text-slate-200">{s.title}</span></div>
                <div className="text-slate-500">time: {s.source_time ? fmtTime(s.source_time) : 'not recorded'} · source: {s.source_id ?? 'n/a'} · status: {s.review_status ?? 'n/a'}</div>
                <div className="mt-1 whitespace-pre-wrap text-slate-300">{s.text}</div>
                {s.link && <Link to={s.link} className="mt-1 inline-block text-accent-400 hover:underline">open record</Link>}
              </div>
            ))}
          </div>
          {answer.differences && answer.differences.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs text-slate-400">{answer.differences.map((d) => <li key={d}>{d}</li>)}</ul>}
          {answer.shared_terms && answer.shared_terms.length > 0 && <p className="mt-1 text-xs text-slate-500">Shared wording: {answer.shared_terms.join(', ')} (overlap only; not agreement)</p>}
        </div>
      )}
      {answer.missing_information.length > 0 && (
        <div><h4 className="mb-1 text-sm font-semibold text-slate-200">Missing information</h4>
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-slate-300">{answer.missing_information.map((m, i) => <li key={i}>{m}</li>)}</ul></div>
      )}
      {answer.uncertainty.length > 0 && (
        <div><h4 className="mb-1 text-sm font-semibold text-slate-200">Uncertainty and limits</h4>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-slate-400">{answer.uncertainty.map((m, i) => <li key={i}>{m}</li>)}</ul></div>
      )}
      {answer.citations.length > 0 && (
        <div><h4 className="mb-1 text-sm font-semibold text-slate-200">Sources ({answer.citations.length})</h4>
          <ul className="space-y-2">{answer.citations.map((c, i) => <CitationCard key={c.id ?? i} c={c} n={i + 1} />)}</ul></div>
      )}
      {answer.retrieval.weak_matches && answer.retrieval.weak_matches.length > 0 && (
        <p className="text-xs text-slate-500">Partial keyword matches (not used as support): {answer.retrieval.weak_matches.map((w) => w.title ?? w.record_id).join('; ')}</p>
      )}
      {answer.followups.length > 0 && onFollowup && (
        <div className="flex flex-wrap gap-2">{answer.followups.map((f) => (
          <button key={f} type="button" onClick={() => onFollowup(f)} className="rounded-sm border border-charcoal-600 px-2 py-1 text-xs text-slate-300 hover:bg-charcoal-700">{f}</button>
        ))}</div>
      )}
    </div>
  )
}

/** Search with filters, excerpts and optional multi-select. All data comes from /retrieval/search. */
export function SearchPanel({ investigationId, selected, onToggle, extra }: {
  investigationId?: string
  selected?: Map<string, SearchHit>
  onToggle?: (h: SearchHit) => void
  extra?: ReactNode
}) {
  const [q, setQ] = useState('')
  const [types, setTypes] = useState<string[]>([])
  const [reviewStatus, setReviewStatus] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [page, setPage] = useState(1)
  const [applied, setApplied] = useState<{ q: string; types: string[]; reviewStatus: string; from: string; to: string } | null>(null)
  const results = useLoad<SearchResponse | null>(
    async () => (applied ? copilotApi.search({ q: applied.q, recordTypes: applied.types, investigationId, reviewStatus: applied.reviewStatus || undefined, timeFrom: applied.from || undefined, timeTo: applied.to || undefined, page }) : null),
    [applied, page, investigationId],
  )
  function submit(e: FormEvent) {
    e.preventDefault()
    if (!q.trim()) return
    setPage(1)
    setApplied({ q: q.trim(), types, reviewStatus, from, to })
  }
  const toggleType = (t: string) => setTypes((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]))
  return (
    <div className="space-y-3">
      <Card>
        <form onSubmit={submit} className="space-y-3">
          <div className="flex gap-2">
            <input className={inputClass} placeholder={investigationId ? 'Search this investigation’s records…' : 'Search authorized records by keyword…'} value={q} onChange={(e) => setQ(e.target.value)} maxLength={500} aria-label="Search query" />
            <Button type="submit" disabled={!q.trim()}>Search</Button>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-400">
            {RECORD_TYPES.map((t) => (
              <label key={t} className="flex items-center gap-1"><input type="checkbox" checked={types.includes(t)} onChange={() => toggleType(t)} />{t === 'scenario' ? 'scenario (SIMULATED, hypothetical; only searched when ticked)' : t.replace(/_/g, ' ')}</label>
            ))}
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <Field label="Review / processing status"><input className={inputClass} value={reviewStatus} onChange={(e) => setReviewStatus(e.target.value)} maxLength={30} placeholder="e.g. ingested, confirmed" /></Field>
            <Field label="Record time from"><input type="datetime-local" className={inputClass} value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="Record time to"><input type="datetime-local" className={inputClass} value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          </div>
          {extra}
        </form>
      </Card>
      <LoadState loading={results.loading && !!applied} error={results.error}>
        {!applied && <EmptyState message="Enter keywords to search records you are authorized to read." />}
        {results.data && (
          <>
            <Notice>{results.data.method.ranking_note} {results.data.method.semantic_note}</Notice>
            {results.data.notice && <Notice tone="warn">{results.data.notice}</Notice>}
            {results.data.candidates_truncated && <Notice tone="warn">Many records matched; only the most recently indexed candidates were ranked.</Notice>}
            {results.data.items.length === 0 ? <EmptyState message="No authorized records matched." /> : (
              <Card>
                <ul className="divide-y divide-charcoal-700 text-sm">
                  {results.data.items.map((h) => (
                    <li key={hitKey(h)} className="py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        {onToggle && <input type="checkbox" aria-label={`Select ${h.title ?? h.record_id}`} checked={!!selected?.has(hitKey(h))} onChange={() => onToggle(h)} />}
                        <StatusPill status={h.record_type} />
                        {h.link ? <Link to={h.link} className="text-accent-400 hover:underline">{h.title ?? h.record_id}</Link> : <span className="text-slate-200">{h.title ?? h.record_id}</span>}
                        {h.review_status && <StatusPill status={h.review_status} />}
                        {!h.content_available && <span className="text-xs text-status-warning">metadata only</span>}
                        {h.stale && <span className="text-xs text-status-warning">changed since indexed</span>}
                        <span className="ml-auto text-xs text-slate-500" title="BM25 keyword relevance; not a probability of correctness">relevance {h.score.toFixed(2)}</span>
                      </div>
                      <div className="mt-1 whitespace-pre-wrap text-xs text-slate-300">{h.excerpt}</div>
                      <div className="text-xs text-slate-500">
                        matched: {h.matched_terms.join(', ')} · {h.source_time ? `record time ${fmtTime(h.source_time)}` : 'no record time'} · version {h.document_version}
                        {h.section && ` · section "${h.section}"`} · {h.matching_chunks} matching passage(s) · <Mono>{h.record_id}</Mono>
                      </div>
                    </li>
                  ))}
                </ul>
                <Pagination page={results.data.page} pageSize={results.data.page_size} total={results.data.total} onPageChange={setPage} />
              </Card>
            )}
          </>
        )}
      </LoadState>
    </div>
  )
}
