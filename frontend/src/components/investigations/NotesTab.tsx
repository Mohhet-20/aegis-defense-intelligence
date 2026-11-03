import { useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import type { InvestigationNote, NoteRevision } from '../../types/workspace'
import { Button, Card, EmptyState, ErrorState, Field, StatusPill, inputClass } from '../ui/Primitives'
import { LoadState, Notice } from './InvestigationBits'
import { fmtTime, useLoad, errorText } from './useLoad'

const KIND_LABEL: Record<string, string> = {
  observed_fact: 'Observed fact',
  analyst_interpretation: 'Analyst interpretation',
  hypothesis: 'Hypothesis (unresolved)',
  review_question: 'Review question',
}

export function NotesPanel({ investigationId, evidenceId, canWrite, readOnly }: { investigationId: string; evidenceId?: string; canWrite: boolean; readOnly?: boolean }) {
  const notes = useLoad(() => api.workspace.notes(investigationId, evidenceId), [investigationId, evidenceId])
  const kinds = useLoad(() => api.workspace.noteKinds(investigationId), [investigationId])
  const [body, setBody] = useState('')
  const [kind, setKind] = useState('analyst_interpretation')
  const [tags, setTags] = useState('')
  const [replyTo, setReplyTo] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<InvestigationNote | null>(null)
  const [editBody, setEditBody] = useState('')
  const [history, setHistory] = useState<{ id: string; revisions: NoteRevision[] } | null>(null)
  const editable = canWrite && !readOnly

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await api.workspace.createNote(investigationId, {
        body, note_kind: replyTo ? 'observed_fact' : kind, evidence_id: evidenceId, parent_note_id: replyTo ?? undefined,
        tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
      })
      setBody(''); setTags(''); setReplyTo(null)
      notes.reload()
    } catch (err) { setError(errorText(err, 'Could not save note.')) }
  }

  async function saveEdit() {
    if (!editing) return
    setError(null)
    try {
      await api.workspace.updateNote(investigationId, editing.id, { expected_version: editing.version, body: editBody })
      setEditing(null)
      notes.reload()
    } catch (err) {
      setError(errorText(err, 'Could not save edit.'))
      notes.reload() // a 409 means someone else changed it: show the current version
    }
  }

  async function setResolution(n: InvestigationNote, status: string) {
    setError(null)
    try {
      await api.workspace.updateNote(investigationId, n.id, { expected_version: n.version, resolution_status: status })
      notes.reload()
    } catch (err) { setError(errorText(err, 'Could not update.')); notes.reload() }
  }

  async function showHistory(n: InvestigationNote) {
    if (history?.id === n.id) return setHistory(null)
    setHistory({ id: n.id, revisions: await api.workspace.noteRevisions(investigationId, n.id) })
  }

  const top = (notes.data ?? []).filter((n) => !n.parent_note_id)
  const replies = (id: string) => (notes.data ?? []).filter((n) => n.parent_note_id === id)

  function NoteCard({ n }: { n: InvestigationNote }) {
    return (
      <div className="rounded-md border border-charcoal-700 p-3 text-sm">
        <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <StatusPill status={n.note_kind} />
          <span>{KIND_LABEL[n.note_kind]}</span>
          <span>v{n.version}</span>
          <span>{fmtTime(n.created_at)}</span>
          {n.resolution_status && <StatusPill status={n.resolution_status} />}
          {n.tags.map((t) => <span key={t} className="rounded-sm bg-charcoal-700 px-1.5">{t}</span>)}
        </div>
        {editing?.id === n.id ? (
          <div className="space-y-2">
            <textarea className={inputClass} rows={3} value={editBody} onChange={(e) => setEditBody(e.target.value)} />
            <div className="flex gap-2"><Button onClick={saveEdit}>Save (as v{n.version + 1})</Button><Button variant="secondary" onClick={() => setEditing(null)}>Cancel</Button></div>
          </div>
        ) : <p className="whitespace-pre-wrap text-slate-200">{n.body}</p>}
        <div className="mt-2 flex flex-wrap gap-3 text-xs">
          {editable && editing?.id !== n.id && <button className="text-accent-400 hover:underline" onClick={() => { setEditing(n); setEditBody(n.body) }}>Edit</button>}
          {editable && !n.parent_note_id && <button className="text-accent-400 hover:underline" onClick={() => setReplyTo(n.id)}>Reply</button>}
          {editable && n.note_kind === 'review_question' && n.resolution_status === 'open' && <button className="text-accent-400 hover:underline" onClick={() => setResolution(n, 'resolved')}>Mark resolved</button>}
          {editable && n.note_kind === 'review_question' && n.resolution_status !== 'open' && <button className="text-accent-400 hover:underline" onClick={() => setResolution(n, 'open')}>Reopen</button>}
          <button className="text-slate-400 hover:underline" onClick={() => showHistory(n)}>{history?.id === n.id ? 'Hide history' : 'Version history'}</button>
        </div>
        {history?.id === n.id && (
          <ol className="mt-2 space-y-1 border-l border-charcoal-600 pl-3 text-xs text-slate-400">
            {history.revisions.map((r) => <li key={r.version}><span className="text-slate-500">v{r.version} · {fmtTime(r.created_at)}</span><div className="whitespace-pre-wrap">{r.body}</div></li>)}
          </ol>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <Notice>Notes are separate records. They never change evidence or model outputs. Edits are saved as new versions; if someone else edited first you will be told and shown the current text instead of overwriting it.</Notice>
      {error && <ErrorState message={error} />}
      {editable && (
        <Card>
          <form onSubmit={submit} className="space-y-3">
            {replyTo ? <p className="text-xs text-slate-400">Replying to a note. <button type="button" className="text-accent-400" onClick={() => setReplyTo(null)}>Cancel reply</button></p> : (
              <Field label="Type">
                <select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value)}>
                  {(kinds.data ?? []).map((k) => <option key={k.kind} value={k.kind}>{KIND_LABEL[k.kind] ?? k.kind} -- {k.description}</option>)}
                </select>
              </Field>
            )}
            <Field label="Note"><textarea className={inputClass} rows={3} value={body} onChange={(e) => setBody(e.target.value)} required maxLength={8000} /></Field>
            <Field label="Tags (comma separated)"><input className={inputClass} value={tags} onChange={(e) => setTags(e.target.value)} /></Field>
            <Button type="submit">{replyTo ? 'Post reply' : 'Add note'}</Button>
          </form>
        </Card>
      )}
      <LoadState loading={notes.loading} error={notes.error}>
        {top.length === 0 ? <EmptyState message="No notes yet." /> : (
          <div className="space-y-3">
            {top.map((n) => (
              <div key={n.id} className="space-y-2">
                <NoteCard n={n} />
                {replies(n.id).map((r) => <div key={r.id} className="ml-6"><NoteCard n={r} /></div>)}
              </div>
            ))}
          </div>
        )}
      </LoadState>
    </div>
  )
}
