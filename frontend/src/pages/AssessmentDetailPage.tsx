import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { Assessment, AssessmentEvidenceLink, AssessmentRevision } from '../types/api'
import { AssessmentAdvisoryPanel } from '../components/analytics/AssessmentAdvisoryPanel'
import { Button, Card, ErrorState, Field, PageHeader, Spinner, StatusPill, inputClass } from '../components/ui/Primitives'

const CONFIDENCE_LEVELS = ['low', 'moderate', 'high']
const STATUS_OPTIONS = ['draft', 'in_review', 'published', 'archived']

export function AssessmentDetailPage() {
  const { assessmentId } = useParams<{ assessmentId: string }>()
  const { user } = useAuth()
  const [assessment, setAssessment] = useState<Assessment | null>(null)
  const [links, setLinks] = useState<AssessmentEvidenceLink[] | null>(null)
  const [revisions, setRevisions] = useState<AssessmentRevision[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [summary, setSummary] = useState('')
  const [assumptionsText, setAssumptionsText] = useState('')
  const [gapsText, setGapsText] = useState('')
  const [confidenceLevel, setConfidenceLevel] = useState('')
  const [confidenceRationale, setConfidenceRationale] = useState('')
  const [editing, setEditing] = useState(false)

  const [linkRole, setLinkRole] = useState('supporting')
  const [linkEventId, setLinkEventId] = useState('')
  const [linkNote, setLinkNote] = useState('')

  const canManage = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  function load() {
    if (!assessmentId) return
    api.assessments
      .get(assessmentId)
      .then((a) => {
        setAssessment(a)
        setSummary(a.summary ?? '')
        setAssumptionsText(a.assumptions.join('\n'))
        setGapsText(a.information_gaps.join('\n'))
        setConfidenceLevel(a.confidence_level ?? '')
        setConfidenceRationale(a.confidence_rationale ?? '')
        setError(null)
      })
      .catch((e) => setError(e.message))
    api.assessments.listEvidenceLinks(assessmentId).then(setLinks).catch(() => setLinks([]))
    api.assessments.revisions(assessmentId).then(setRevisions).catch(() => setRevisions([]))
  }

  useEffect(load, [assessmentId])

  async function saveContent(e: FormEvent) {
    e.preventDefault()
    if (!assessmentId) return
    setActionError(null)
    try {
      await api.assessments.update(assessmentId, {
        summary: summary || null,
        assumptions: assumptionsText.split('\n').map((s) => s.trim()).filter(Boolean),
        information_gaps: gapsText.split('\n').map((s) => s.trim()).filter(Boolean),
        confidence_level: confidenceLevel || null,
        confidence_rationale: confidenceRationale || null,
        change_note: 'Updated analysis content.',
      })
      setEditing(false)
      load()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not save changes.')
    }
  }

  async function transition(status: string) {
    if (!assessmentId) return
    setActionError(null)
    try {
      await api.assessments.update(assessmentId, { status, change_note: `Status -> ${status}` })
      load()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : `Could not move to ${status}.`)
    }
  }

  async function addLink(e: FormEvent) {
    e.preventDefault()
    if (!assessmentId) return
    setActionError(null)
    try {
      await api.assessments.linkEvidence(assessmentId, { role: linkRole, event_id: linkEventId, note: linkNote || undefined })
      setLinkEventId('')
      setLinkNote('')
      load()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not link evidence.')
    }
  }

  if (error) return <ErrorState message={error} />
  if (!assessment) return <Spinner />

  const supporting = links?.filter((l) => l.role === 'supporting') ?? []
  const contradicting = links?.filter((l) => l.role === 'contradicting') ?? []

  return (
    <div>
      <PageHeader
        title={assessment.title}
        description={
          <>
            <Link to="/fusion/assessments" className="text-accent-400 hover:underline">
              Assessment Workspace
            </Link>{' '}
            / {assessment.id} · version {assessment.version}
          </>
        }
        actions={<StatusPill status={assessment.status} />}
      />

      {actionError && <ErrorState message={actionError} />}

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Question</h2>
          <p className="text-sm text-slate-300">{assessment.question}</p>
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Status</h2>
          <div className="mb-3 flex gap-2">
            <StatusPill status={assessment.status} />
            {assessment.confidence_level && <StatusPill status={assessment.confidence_level} />}
          </div>
          {canManage && (
            <div className="flex flex-wrap gap-1.5">
              {STATUS_OPTIONS.filter((s) => s !== assessment.status).map((s) => (
                <Button key={s} variant="secondary" onClick={() => transition(s)}>
                  → {s}
                </Button>
              ))}
            </div>
          )}
          <p className="mt-2 text-xs text-slate-500">
            Allowed transitions are enforced by the server (draft→in_review→published→archived); an invalid move is rejected, not silently applied.
          </p>
        </Card>

        <Card className="md:col-span-2">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-200">Analysis</h2>
            {canManage && !editing && <Button variant="secondary" onClick={() => setEditing(true)}>Edit</Button>}
          </div>

          {!editing && (
            <>
              <p className="mb-3 text-sm text-slate-300">{assessment.summary ?? 'No summary written yet.'}</p>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Assumptions</h3>
                  {assessment.assumptions.length === 0 ? (
                    <p className="text-xs text-slate-500">None stated.</p>
                  ) : (
                    <ul className="list-inside list-disc text-sm text-slate-300">
                      {assessment.assumptions.map((a, i) => <li key={i}>{a}</li>)}
                    </ul>
                  )}
                </div>
                <div>
                  <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Information gaps</h3>
                  {assessment.information_gaps.length === 0 ? (
                    <p className="text-xs text-slate-500">None stated.</p>
                  ) : (
                    <ul className="list-inside list-disc text-sm text-slate-300">
                      {assessment.information_gaps.map((g, i) => <li key={i}>{g}</li>)}
                    </ul>
                  )}
                </div>
              </div>
              <h3 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Confidence rationale</h3>
              <p className="text-sm text-slate-300">{assessment.confidence_rationale ?? 'Not stated -- confidence is never inferred automatically.'}</p>
            </>
          )}

          {editing && (
            <form onSubmit={saveContent} className="space-y-3">
              <Field label="Summary">
                <textarea className={inputClass} rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} />
              </Field>
              <Field label="Assumptions (one per line)">
                <textarea className={inputClass} rows={3} value={assumptionsText} onChange={(e) => setAssumptionsText(e.target.value)} />
              </Field>
              <Field label="Information gaps (one per line)">
                <textarea className={inputClass} rows={3} value={gapsText} onChange={(e) => setGapsText(e.target.value)} />
              </Field>
              <Field label="Confidence level (qualitative only -- never a fabricated number)">
                <select className={inputClass} value={confidenceLevel} onChange={(e) => setConfidenceLevel(e.target.value)}>
                  <option value="">not set</option>
                  {CONFIDENCE_LEVELS.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Confidence rationale">
                <textarea className={inputClass} rows={2} value={confidenceRationale} onChange={(e) => setConfidenceRationale(e.target.value)} />
              </Field>
              <div className="flex gap-2">
                <Button type="submit">Save</Button>
                <Button variant="secondary" onClick={() => setEditing(false)}>Cancel</Button>
              </div>
            </form>
          )}
        </Card>

        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Supporting evidence</h2>
          {supporting.length === 0 ? (
            <p className="text-sm text-slate-500">None linked.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {supporting.map((l) => (
                <li key={l.id}>
                  {l.event_id ? (
                    <Link to={`/events/${l.event_id}`} className="font-mono text-xs text-accent-400 hover:underline">
                      event:{l.event_id.slice(0, 8)}
                    </Link>
                  ) : (
                    <span className="font-mono text-xs text-slate-400">evidence:{l.evidence_id?.slice(0, 8)}</span>
                  )}
                  {l.note && <span className="ml-2 text-xs text-slate-500">{l.note}</span>}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Contradicting evidence</h2>
          {contradicting.length === 0 ? (
            <p className="text-sm text-slate-500">None linked.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {contradicting.map((l) => (
                <li key={l.id}>
                  {l.event_id ? (
                    <Link to={`/events/${l.event_id}`} className="font-mono text-xs text-accent-400 hover:underline">
                      event:{l.event_id.slice(0, 8)}
                    </Link>
                  ) : (
                    <span className="font-mono text-xs text-slate-400">evidence:{l.evidence_id?.slice(0, 8)}</span>
                  )}
                  {l.note && <span className="ml-2 text-xs text-slate-500">{l.note}</span>}
                </li>
              ))}
            </ul>
          )}
        </Card>

        {canManage && (
          <Card className="md:col-span-2">
            <h2 className="mb-2 text-sm font-semibold text-slate-200">Link evidence</h2>
            <form onSubmit={addLink} className="flex flex-wrap items-end gap-3">
              <Field label="Role">
                <select className={inputClass} value={linkRole} onChange={(e) => setLinkRole(e.target.value)}>
                  <option value="supporting">supporting</option>
                  <option value="contradicting">contradicting</option>
                </select>
              </Field>
              <Field label="Event ID">
                <input className={inputClass} value={linkEventId} onChange={(e) => setLinkEventId(e.target.value)} required placeholder="event id this links to" />
              </Field>
              <Field label="Note (optional)">
                <input className={inputClass} value={linkNote} onChange={(e) => setLinkNote(e.target.value)} />
              </Field>
              <Button type="submit">Link</Button>
            </form>
          </Card>
        )}

        <div className="md:col-span-2">
          <AssessmentAdvisoryPanel assessmentId={assessment.id} assessmentVersion={assessment.version} />
        </div>

        <Card className="md:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Version history</h2>
          {revisions === null && <Spinner />}
          {revisions && revisions.length === 0 && <p className="text-sm text-slate-500">No revisions yet -- this is the first version.</p>}
          {revisions && revisions.length > 0 && (
            <ul className="space-y-2">
              {revisions.map((r) => (
                <li key={r.id} className="border-b border-charcoal-700/50 py-2 text-sm last:border-0">
                  <div className="flex justify-between">
                    <span className="text-slate-300">Version {r.version} (pre-update snapshot)</span>
                    <span className="text-xs text-slate-500">{new Date(r.created_at).toLocaleString()}</span>
                  </div>
                  {r.change_note && <div className="text-xs text-slate-500">{r.change_note}</div>}
                  <pre className="mt-1 overflow-x-auto rounded-md bg-navy-950 p-2 text-xs text-slate-500">{JSON.stringify(r.snapshot, null, 2)}</pre>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}
