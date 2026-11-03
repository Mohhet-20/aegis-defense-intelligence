import { useState } from 'react'
import { api } from '../../api/client'
import { copilotApi } from '../../api/copilot'
import { hitKey, type Answer, type AskRequest, type SearchHit } from '../../types/copilot'
import { Button, Card, Field, inputClass } from '../ui/Primitives'
import { AnswerView, SearchPanel } from '../copilot/CopilotBits'
import { LoadState, Notice } from './InvestigationBits'
import { errorText } from './useLoad'

/** Investigation-scoped copilot: scoped search, summary, chronology, selected-record comparison and an editable report draft. */
export function CopilotTab({ investigationId, canWrite, readOnly }: { investigationId: string; canWrite: boolean; readOnly: boolean }) {
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [question, setQuestion] = useState('')
  const [selected, setSelected] = useState<Map<string, SearchHit>>(new Map())
  const [draft, setDraft] = useState<string | null>(null)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)

  async function run(body: AskRequest) {
    setBusy(true)
    setError(null)
    setSaveMsg(null)
    setAnswer(null)
    try {
      const res = await copilotApi.ask({ investigation_id: investigationId, save: false, ...body })
      setAnswer(res.answer)
      setDraft(res.answer.draft_markdown ?? null)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  const toggle = (h: SearchHit) => setSelected((m) => {
    const n = new Map(m)
    if (n.has(hitKey(h))) n.delete(hitKey(h))
    else n.set(hitKey(h), h)
    return n
  })
  const refs = [...selected.values()].map((h) => ({ record_type: h.record_type, record_id: h.record_id }))

  function download() {
    if (!draft) return
    const url = URL.createObjectURL(new Blob([draft], { type: 'text/markdown' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `draft-report-${investigationId}.md`
    a.click()
    URL.revokeObjectURL(url)
  }
  async function saveAsNote() {
    if (!draft) return
    try {
      await api.workspace.createNote(investigationId, { body: draft.slice(0, 8000), note_kind: 'analyst_interpretation', tags: ['copilot-draft'] })
      setSaveMsg(draft.length > 8000 ? 'Saved as a note (truncated to the 8000-character note limit).' : 'Saved as an analyst note. It is your edited text, not a verified finding.')
    } catch (e) {
      setSaveMsg(errorText(e, 'Could not save the note.'))
    }
  }

  return (
    <div className="space-y-4">
      <Notice>
        The copilot works only from records in this investigation that you can access. Summaries are assembled from stored fields and cite their records; conflicts are shown, not resolved.
      </Notice>
      <Card>
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy} onClick={() => void run({ task: 'summarize_investigation' })}>Summarize investigation</Button>
          <Button variant="secondary" disabled={busy} onClick={() => void run({ task: 'chronology' })}>Chronological overview</Button>
          <Button variant="secondary" disabled={busy} onClick={() => void run({ task: 'report_draft' })}>Draft report</Button>
          <Button variant="secondary" disabled={busy || refs.length < 2 || refs.length > 6} onClick={() => void run({ task: 'compare', record_refs: refs })}>Compare selected ({refs.length})</Button>
        </div>
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (question.trim()) void run({ task: 'question', question: question.trim() }) }}>
          <input className={inputClass} placeholder="Ask about this investigation’s records…" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={2000} aria-label="Question" />
          <Button type="submit" disabled={busy || !question.trim()}>Ask</Button>
        </form>
      </Card>
      <LoadState loading={busy} error={error}>
        {answer && (
          <Card>
            <AnswerView answer={answer} />
            {draft !== null && (
              <div className="mt-4 space-y-2 border-t border-charcoal-700 pt-3">
                <Field label="Report draft (editable before saving or exporting)">
                  <textarea className={`${inputClass} font-mono`} rows={18} value={draft} onChange={(e) => setDraft(e.target.value)} />
                </Field>
                <div className="flex flex-wrap gap-2">
                  <Button variant="secondary" onClick={download}>Download as Markdown</Button>
                  {canWrite && !readOnly && <Button onClick={() => void saveAsNote()}>Save as analyst note</Button>}
                </div>
                {saveMsg && <Notice>{saveMsg}</Notice>}
              </div>
            )}
          </Card>
        )}
      </LoadState>
      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-200">Search within this investigation</h3>
        <SearchPanel investigationId={investigationId} selected={selected} onToggle={toggle} />
        <p className="mt-2 text-xs text-slate-500">Tick results to compare them or include them in a comparison.</p>
      </div>
    </div>
  )
}
