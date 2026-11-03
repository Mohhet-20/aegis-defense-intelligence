import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import { copilotApi } from '../api/copilot'
import { AnswerView, SearchPanel } from '../components/copilot/CopilotBits'
import { Pagination } from '../components/tables/DataTable'
import { LoadState, Notice } from '../components/investigations/InvestigationBits'
import { errorText, fmtTime, useLoad } from '../components/investigations/useLoad'
import { Button, Card, EmptyState, Field, PageHeader, StatusPill, Tabs, inputClass } from '../components/ui/Primitives'
import { hitKey, type Answer, type Capabilities, type ConversationDetail, type EvalResult, type IndexRunResult, type SearchHit } from '../types/copilot'

interface Exchange { question: string; answer: Answer }

function CapabilityBanner({ caps }: { caps: Capabilities }) {
  return (
    <Notice tone={caps.generation.available ? 'info' : 'warn'}>
      Keyword search: available. Semantic search: {caps.semantic_search.available ? 'available' : `unavailable (${caps.semantic_search.reason})`}.{' '}
      Generative answers: {caps.generation.available ? `available via ${caps.generation.provider}${caps.generation.external ? ' (external service: excerpts you can read are sent to it)' : ''}` : `unavailable (${caps.generation.reason ?? 'not configured'}). Answers show cited source excerpts only.`}
    </Notice>
  )
}

function AskTab({ caps, initialConversation }: { caps: Capabilities; initialConversation: string | null }) {
  const [question, setQuestion] = useState('')
  const [investigationId, setInvestigationId] = useState('')
  const [thread, setThread] = useState<Exchange[]>([])
  const [conversationId, setConversationId] = useState<string | null>(initialConversation)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const invs = useLoad(() => api.workspace.list({ pageSize: 100 }), [])

  useEffect(() => {
    if (!initialConversation) return
    let live = true
    copilotApi.conversation(initialConversation).then((c: ConversationDetail) => {
      if (!live) return
      const ex: Exchange[] = []
      for (let i = 0; i + 1 < c.messages.length; i += 2) {
        const a = c.messages[i + 1].answer
        if (a) ex.push({ question: c.messages[i].content ?? `[${c.messages[i].task}]`, answer: a })
      }
      setThread(ex)
      setInvestigationId(c.investigation_id ?? '')
    }).catch((e) => live && setError(e))
    return () => { live = false }
  }, [initialConversation])

  async function ask(q: string) {
    if (!q.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      const res = await copilotApi.ask({ task: 'question', question: q.trim(), investigation_id: investigationId || undefined, conversation_id: conversationId ?? undefined })
      setThread((t) => [...t, { question: q.trim(), answer: res.answer }])
      setConversationId(res.conversation_id)
      setQuestion('')
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); void ask(question) }

  return (
    <div className="space-y-3">
      <CapabilityBanner caps={caps} />
      <Card>
        <form onSubmit={submit} className="space-y-3">
          <Field label="Question about records you can access">
            <textarea className={inputClass} rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={caps.limits.max_question_chars} placeholder="e.g. What did the north gate camera record?" />
          </Field>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Limit to investigation (optional)">
              <select className={inputClass} value={investigationId} onChange={(e) => setInvestigationId(e.target.value)}>
                <option value="">All accessible records</option>
                {(invs.data?.items ?? []).map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}
              </select>
            </Field>
            <Button type="submit" disabled={busy || !question.trim()}>{busy ? 'Retrieving…' : 'Ask'}</Button>
            {thread.length > 0 && <Button variant="secondary" onClick={() => { setThread([]); setConversationId(null) }}>New conversation</Button>}
          </div>
        </form>
      </Card>
      {error != null && <div role="alert" className="rounded-md border border-status-critical/30 bg-status-critical/10 px-3 py-2 text-sm text-status-critical">
        {error instanceof ApiError && error.status === 429 ? 'Too many requests. Please wait a moment and try again.' : errorText(error, 'The question could not be answered.')}
      </div>}
      {thread.length === 0 && !busy && <EmptyState message="Ask a question. Answers are built from retrieved records and cite their sources." />}
      {thread.map((ex, i) => (
        <Card key={i}>
          <div className="mb-3 text-sm font-medium text-slate-100">Q: {ex.question}</div>
          <AnswerView answer={ex.answer} onFollowup={(f) => setQuestion(f)} />
        </Card>
      ))}
      <p className="text-xs text-slate-500">History is not evidence. Past answers are re-checked against your current access whenever a conversation is opened.</p>
    </div>
  )
}

function CompareTab({ selected, remove, clear }: { selected: Map<string, SearchHit>; remove: (k: string) => void; clear: () => void }) {
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const items = [...selected.values()]
  async function run(task: 'compare' | 'related') {
    setBusy(true)
    setError(null)
    setAnswer(null)
    try {
      const res = await copilotApi.ask({ task, record_refs: items.map((h) => ({ record_type: h.record_type, record_id: h.record_id })), save: false })
      setAnswer(res.answer)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-3">
      <Card>
        <h3 className="mb-2 text-sm font-semibold text-slate-200">Selected records ({items.length})</h3>
        {items.length === 0 ? <p className="text-sm text-slate-500">Select 2–6 results in the Search tab to compare them side by side, or one to find related records.</p> : (
          <ul className="mb-3 divide-y divide-charcoal-700 text-sm">
            {items.map((h) => (
              <li key={hitKey(h)} className="flex items-center gap-2 py-1">
                <StatusPill status={h.record_type} /><span className="text-slate-200">{h.title ?? h.record_id}</span>
                <button type="button" className="ml-auto text-xs text-slate-400 hover:text-slate-200" onClick={() => remove(hitKey(h))}>remove</button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <Button disabled={busy || items.length < 2 || items.length > 6} onClick={() => void run('compare')}>Compare side by side</Button>
          <Button variant="secondary" disabled={busy || items.length !== 1} onClick={() => void run('related')}>Find related records</Button>
          {items.length > 0 && <Button variant="secondary" onClick={clear}>Clear</Button>}
        </div>
      </Card>
      <LoadState loading={busy} error={error}>
        {answer && <Card><AnswerView answer={answer} /></Card>}
      </LoadState>
    </div>
  )
}

function HistoryTab({ onOpen }: { onOpen: (id: string) => void }) {
  const [page, setPage] = useState(1)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const list = useLoad(() => copilotApi.conversations(page), [page])
  async function del(id: string) {
    try {
      await copilotApi.deleteConversation(id)
      setConfirm(null)
      list.reload()
    } catch (e) {
      setErr(e)
    }
  }
  return (
    <LoadState loading={list.loading} error={list.error}>
      {err != null && <Notice tone="warn">{errorText(err, 'Delete failed.')}</Notice>}
      {list.data && list.data.items.length === 0 ? <EmptyState message="No saved conversations." /> : (
        <Card>
          <ul className="divide-y divide-charcoal-700 text-sm">
            {(list.data?.items ?? []).map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-2 py-2">
                <span className="text-slate-200">{c.title ?? 'Untitled conversation'}</span>
                <span className="text-xs text-slate-500">{c.message_count} messages · updated {fmtTime(c.updated_at)}</span>
                <span className="ml-auto flex gap-2">
                  <Button variant="secondary" onClick={() => onOpen(c.id)}>Open</Button>
                  {confirm === c.id ? <Button variant="danger" onClick={() => void del(c.id)}>Confirm delete</Button> : <Button variant="secondary" onClick={() => setConfirm(c.id)}>Delete</Button>}
                </span>
              </li>
            ))}
          </ul>
          {list.data && <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onPageChange={setPage} />}
          <p className="mt-2 text-xs text-slate-500">Deleting permanently removes the conversation and its messages. Conversations are private to you.</p>
        </Card>
      )}
    </LoadState>
  )
}

function AdminTab({ caps }: { caps: Capabilities }) {
  const status = useLoad(() => copilotApi.indexStatus(), [])
  const [run, setRun] = useState<IndexRunResult | null>(null)
  const [ev, setEv] = useState<EvalResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  async function act<T>(fn: () => Promise<T>, set: (v: T) => void) {
    setBusy(true)
    setError(null)
    try {
      set(await fn())
      status.reload()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-3">
      <Card>
        <h3 className="mb-2 text-sm font-semibold text-slate-200">Index status</h3>
        <LoadState loading={status.loading} error={status.error}>
          {status.data && (
            <div className="space-y-1 text-sm text-slate-300">
              <div>Chunks: {status.data.chunk_count} · stale documents: {status.data.stale_documents}</div>
              <div>By status: {Object.entries(status.data.documents_by_status).map(([k, v]) => `${k} ${v}`).join(', ') || 'none'}</div>
              <div>By type: {Object.entries(status.data.documents_by_type).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(', ') || 'none'}</div>
              <div>Last run: {status.data.last_run ? `${status.data.last_run.status} at ${fmtTime(status.data.last_run.started_at)} (${Object.entries(status.data.last_run.counts).map(([k, v]) => `${k} ${v}`).join(', ')})` : 'never'}</div>
              {status.data.errors.length > 0 && <ul className="list-disc pl-5 text-xs text-status-warning">{status.data.errors.map((e) => <li key={e.record_id}>{e.record_type} {e.record_id}: {e.error}</li>)}</ul>}
            </div>
          )}
        </LoadState>
        <div className="mt-3 flex gap-2">
          <Button disabled={busy} onClick={() => void act(() => copilotApi.runIndex(), setRun)}>{busy ? 'Working…' : 'Index / refresh all records'}</Button>
          <Button variant="secondary" disabled={busy} onClick={() => void act(() => copilotApi.purge(), () => undefined)}>Purge expired tombstones &amp; conversations</Button>
        </div>
        {run && <Notice>Run {run.status}: {Object.entries(run.counts).map(([k, v]) => `${k} ${v}`).join(', ')}{run.errors.length ? ` · ${run.errors.length} error(s)` : ''}</Notice>}
      </Card>
      {caps.can_evaluate && (
        <Card>
          <h3 className="mb-2 text-sm font-semibold text-slate-200">Retrieval evaluation (synthetic fixtures)</h3>
          <Button disabled={busy} onClick={() => void act(() => copilotApi.evaluate(), setEv)}>Run evaluation</Button>
          {ev && (
            <div className="mt-3 space-y-2 text-sm text-slate-300">
              <Notice tone="warn">{ev.disclaimer}</Notice>
              <div>Dataset {ev.dataset}: {ev.documents} documents, {ev.queries} queries · MRR {ev.retrieval.mrr ?? 'n/a'}</div>
              <div className="text-xs">{Object.entries(ev.retrieval.mean).map(([k, v]) => `${k}=${v ?? 'n/a'}`).join(' · ')}</div>
              <ul className="list-disc pl-5 text-xs">{Object.entries(ev.answer_checks).map(([k, v]) => <li key={k}>{k.replace(/_/g, ' ')}: {typeof v === 'boolean' ? (v ? 'pass' : 'FAIL') : `${v.passed}/${v.total}`}</li>)}</ul>
            </div>
          )}
        </Card>
      )}
      {error != null && <div role="alert" className="rounded-md border border-status-critical/30 bg-status-critical/10 px-3 py-2 text-sm text-status-critical">{errorText(error, 'Request failed.')}</div>}
    </div>
  )
}

export function CopilotPage() {
  const caps = useLoad(() => copilotApi.capabilities(), [])
  const [tab, setTab] = useState('ask')
  const [selected, setSelected] = useState<Map<string, SearchHit>>(new Map())
  const [openConv, setOpenConv] = useState<string | null>(null)
  const toggle = (h: SearchHit) => setSelected((m) => {
    const n = new Map(m)
    if (n.has(hitKey(h))) n.delete(hitKey(h))
    else n.set(hitKey(h), h)
    return n
  })
  const tabs = [
    { key: 'ask', label: 'Ask the copilot' }, { key: 'search', label: 'Search' },
    { key: 'compare', label: `Compare (${selected.size})` }, { key: 'history', label: 'Conversations' },
    ...(caps.data?.can_index ? [{ key: 'admin', label: 'Index & evaluation' }] : []),
  ]
  return (
    <div>
      <PageHeader title="Intelligence Copilot" description="Search records you are authorized to read and ask questions grounded in them. Every statement is tied to a source you can open; the copilot never decides which source is right." />
      <LoadState loading={caps.loading && !caps.data} error={caps.error}>
        {caps.data && (
          <>
            <Tabs tabs={tabs} active={tab} onChange={setTab} />
            {tab === 'ask' && <AskTab key={openConv ?? 'new'} caps={caps.data} initialConversation={openConv} />}
            {tab === 'search' && <><CapabilityBanner caps={caps.data} /><SearchPanel selected={selected} onToggle={toggle} /></>}
            {tab === 'compare' && <CompareTab selected={selected} remove={(k) => setSelected((m) => { const n = new Map(m); n.delete(k); return n })} clear={() => setSelected(new Map())} />}
            {tab === 'history' && <HistoryTab onOpen={(id) => { setOpenConv(id); setTab('ask') }} />}
            {tab === 'admin' && caps.data.can_index && <AdminTab caps={caps.data} />}
          </>
        )}
      </LoadState>
    </div>
  )
}
