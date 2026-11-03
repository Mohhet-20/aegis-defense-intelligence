import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/auth'
import type { AssessmentScoreSnapshot, ReviewDecision, ReviewSummary } from '../../types/api'
import { ApiErrorView } from './AnalyticsBits'
import { Button, Card, Field, Spinner, StatusPill, inputClass } from '../ui/Primitives'

const DECISIONS: { value: ReviewDecision; label: string }[] = [
  { value: 'accepted', label: 'Accept' },
  { value: 'rejected', label: 'Reject' },
  { value: 'further_review_requested', label: 'Request further review' },
]
const FLAGS = [
  { value: 'insufficient_information', label: 'Information is insufficient' },
  { value: 'conflicting_information', label: 'Information is conflicting' },
]

function pretty(v: unknown): string {
  return v === null || v === undefined ? '--' : typeof v === 'object' ? JSON.stringify(v) : String(v)
}

function ConceptRow({ name, value }: { name: string; value: Record<string, unknown> }) {
  const { note, ...rest } = value
  return (
    <div className="border-b border-charcoal-700/50 py-2 text-sm last:border-0">
      <div className="font-medium capitalize text-slate-300">{name.replace(/_/g, ' ')}</div>
      <div className="mt-0.5 font-mono text-xs text-slate-400">
        {Object.entries(rest).map(([k, v]) => `${k}: ${pretty(v)}`).join(' · ')}
      </div>
      {typeof note === 'string' && <div className="text-xs text-slate-500">{note}</div>}
    </div>
  )
}

export function AssessmentAdvisoryPanel({ assessmentId, assessmentVersion }: { assessmentId: string; assessmentVersion: number }) {
  const { user } = useAuth()
  const canReview = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  const [scores, setScores] = useState<AssessmentScoreSnapshot[] | null>(null)
  const [summary, setSummary] = useState<ReviewSummary | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [scoring, setScoring] = useState(false)

  const [decision, setDecision] = useState<ReviewDecision>('further_review_requested')
  const [notes, setNotes] = useState('')
  const [changeReason, setChangeReason] = useState('')
  const [flags, setFlags] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(() => {
    api.analytics.assessments.scores(assessmentId).then(setScores).catch(setError)
    api.analytics.assessments.reviews(assessmentId).then(setSummary).catch(setError)
  }, [assessmentId])
  useEffect(load, [load, assessmentVersion])

  async function computeScore() {
    setScoring(true)
    setActionError(null)
    try {
      await api.analytics.assessments.score(assessmentId)
      load()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Scoring failed.')
    } finally {
      setScoring(false)
    }
  }

  async function submitReview(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setActionError(null)
    try {
      await api.analytics.assessments.submitReview(assessmentId, {
        decision, notes, change_reason: changeReason.trim() || null, information_flags: flags,
      })
      setNotes('')
      setChangeReason('')
      setFlags([])
      load()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not record the review.')
    } finally {
      setSubmitting(false)
    }
  }

  if (error !== null) return <ApiErrorView error={error} />
  if (scores === null || summary === null) return <Spinner />

  const latest = scores[0] ?? null
  const stale = latest !== null && latest.assessment_version !== assessmentVersion
  const needsReason = summary.latest_review !== null && summary.latest_review.decision !== decision

  return (
    <div className="space-y-4">
      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-200">Advisory review priority</h2>
          {canReview && <Button onClick={computeScore} disabled={scoring}>{scoring ? 'Scoring…' : latest ? 'Re-score' : 'Compute score'}</Button>}
        </div>
        <p className="mb-3 rounded-md border border-charcoal-600 bg-navy-950 px-3 py-2 text-xs text-slate-400">
          {latest?.advisory_notice ?? 'Advisory only. A score ranks which assessments most need human review; it is not a finding about any person or event and never triggers an action.'}
        </p>
        {actionError && <div className="mb-2 text-sm text-status-critical">{actionError}</div>}
        {!latest && <p className="text-sm text-slate-500">No score has been computed for this assessment.{canReview ? '' : ' Your role can view scores but not compute them.'}</p>}
        {latest && (
          <>
            <div className="mb-3 flex flex-wrap items-baseline gap-3">
              <span className="text-3xl font-semibold text-slate-100">{latest.score}</span>
              <StatusPill status={latest.priority_band} />
              <span className="text-xs text-slate-500">{latest.score_scale}</span>
            </div>
            <div className="mb-3 text-xs text-slate-500">
              Rule {latest.rule_key} v{latest.rule_version} · assessment version {latest.assessment_version} · computed {new Date(latest.computed_at).toLocaleString()}
            </div>
            {stale && (
              <div className="mb-3 rounded-md border border-status-warning/30 bg-status-warning/10 px-3 py-2 text-xs text-status-warning">
                This score was computed for version {latest.assessment_version}; the assessment is now version {assessmentVersion}. Re-score before relying on it.
              </div>
            )}

            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Contributing factors</h3>
            <table className="mb-4 w-full text-sm">
              <tbody>
                {latest.factors.map((f) => (
                  <tr key={f.key} className="border-t border-charcoal-700/50 align-top">
                    <td className="py-1.5 pr-3">
                      <div className="text-slate-300">{f.label}</div>
                      <div className="text-xs text-slate-500">{f.rationale}</div>
                    </td>
                    <td className="py-1.5 pr-3 font-mono text-xs text-slate-400">input: {pretty(f.input_value)}</td>
                    <td className="w-40 py-1.5">
                      <div className="h-1.5 rounded-sm bg-charcoal-700">
                        <div className="h-1.5 rounded-sm bg-accent-500" style={{ width: `${f.max_points > 0 ? Math.min(100, (f.points / f.max_points) * 100) : 0}%` }} />
                      </div>
                      <div className="mt-0.5 text-xs text-slate-400">{f.points} / {f.max_points} pts</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Kept separate from the score</h3>
                {Object.entries(latest.distinct_concepts).filter(([k]) => k !== 'assessment_priority').map(([k, v]) => <ConceptRow key={k} name={k} value={v} />)}
              </div>
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Uncertainty, conflicts and missing information</h3>
                {latest.conflicts.length === 0 && latest.missing_information.length === 0 && <p className="text-sm text-slate-500">None recorded.</p>}
                <ul className="space-y-1 text-sm">
                  {latest.conflicts.map((c) => (
                    <li key={c.conflict_id} className="text-status-warning">
                      Unresolved conflict <Link to="/fusion/conflicts" className="underline">{c.conflict_id.slice(0, 8)}</Link> on {c.conflicting_fields.map(pretty).join(', ') || 'unspecified fields'}
                    </li>
                  ))}
                  {latest.missing_information.map((m) => (
                    <li key={m.description} className="text-slate-300"><span className="mr-1 text-xs uppercase text-slate-500">{m.source}</span>{m.description}</li>
                  ))}
                </ul>
                <h3 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Data-quality limitations</h3>
                {latest.data_quality_limitations.length === 0 && <p className="text-sm text-slate-500">None detected.</p>}
                <ul className="space-y-1 text-sm text-status-warning">{latest.data_quality_limitations.map((l) => <li key={l.code}>{l.message}</li>)}</ul>
              </div>
            </div>

            <h3 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence and observations considered ({latest.evidence_considered.length})</h3>
            {latest.evidence_considered.length === 0 && <p className="text-sm text-slate-500">Nothing is linked to this assessment.</p>}
            <ul className="space-y-1 text-sm">
              {latest.evidence_considered.map((e) => (
                <li key={String(e.link_id)} className="flex flex-wrap gap-2">
                  <StatusPill status={String(e.role)} />
                  <Link to={e.kind === 'event' ? `/events/${String(e.id)}` : '/fusion/evidence'} className="text-accent-400 hover:underline">{pretty(e.title ?? e.id)}</Link>
                  <span className="text-xs text-slate-500">{String(e.kind)}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>

      <Card>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-200">Human review</h2>
          <StatusPill status={summary.review_status} />
        </div>

        {summary.comparison.available && (
          <div className={`mb-3 rounded-md border px-3 py-2 text-sm ${summary.comparison.agreement === false ? 'border-status-warning/30 bg-status-warning/10 text-status-warning' : 'border-charcoal-600 bg-navy-950 text-slate-300'}`}>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Model output vs human decision</div>
            Advisory: {summary.comparison.advisory_band_at_review ?? 'no score'}{summary.comparison.advisory_score_at_review != null ? ` (${summary.comparison.advisory_score_at_review})` : ''} &rarr; Human: {summary.comparison.human_decision?.replace(/_/g, ' ')}
            <div className="text-xs">{summary.comparison.note}</div>
            {summary.comparison.review_is_for_current_version === false && <div className="text-xs">The latest decision was made on an earlier version of this assessment.</div>}
          </div>
        )}

        {canReview ? (
          <form onSubmit={submitReview} className="mb-4 grid gap-3 md:grid-cols-2">
            <Field label="Decision">
              <select className={inputClass} value={decision} onChange={(e) => setDecision(e.target.value as ReviewDecision)}>
                {DECISIONS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
            </Field>
            <div>
              <span className="mb-1 block text-xs font-medium text-slate-400">Mark information as</span>
              {FLAGS.map((f) => (
                <label key={f.value} className="mr-4 inline-flex items-center gap-1.5 text-sm text-slate-300">
                  <input type="checkbox" checked={flags.includes(f.value)} onChange={(e) => setFlags(e.target.checked ? [...flags, f.value] : flags.filter((x) => x !== f.value))} />
                  {f.label}
                </label>
              ))}
            </div>
            <div className="md:col-span-2">
              <Field label="Reviewer notes (required)">
                <textarea className={`${inputClass} h-20`} value={notes} onChange={(e) => setNotes(e.target.value)} required />
              </Field>
            </div>
            {needsReason && (
              <div className="md:col-span-2">
                <Field label={`Reason for changing the previous decision (${summary.latest_review?.decision.replace(/_/g, ' ')}) -- required`}>
                  <input className={inputClass} value={changeReason} onChange={(e) => setChangeReason(e.target.value)} required />
                </Field>
              </div>
            )}
            <div className="md:col-span-2"><Button type="submit" disabled={submitting || !notes.trim()}>{submitting ? 'Recording…' : 'Record decision'}</Button></div>
          </form>
        ) : (
          <p className="mb-3 text-sm text-slate-500">Your role can read review history but cannot record decisions.</p>
        )}

        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Decision history</h3>
        {summary.history.length === 0 && <p className="text-sm text-slate-500">No decisions recorded yet.</p>}
        <ul className="space-y-2">
          {[...summary.history].reverse().map((r) => (
            <li key={r.id} className="border-b border-charcoal-700/50 pb-2 text-sm last:border-0">
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill status={r.decision} />
                <span className="text-xs text-slate-500">v{r.assessment_version} · {new Date(r.created_at).toLocaleString()}</span>
                {r.advisory_band_at_review && <span className="text-xs text-slate-500">advisory at the time: {r.advisory_band_at_review} ({r.advisory_score_at_review})</span>}
              </div>
              <div className="text-slate-300">{r.notes}</div>
              {r.change_reason && <div className="text-xs text-slate-500">Reason for change: {r.change_reason}</div>}
              {r.information_flags.length > 0 && <div className="text-xs text-status-warning">{r.information_flags.map((f) => f.replace(/_/g, ' ')).join(', ')}</div>}
            </li>
          ))}
        </ul>
      </Card>

      {scores.length > 1 && (
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Score history</h2>
          <ul className="space-y-1 text-sm text-slate-300">
            {scores.map((s) => (
              <li key={s.id}>{new Date(s.computed_at).toLocaleString()} &middot; {s.score} ({s.priority_band}) &middot; v{s.assessment_version} &middot; {s.rule_key} v{s.rule_version}</li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
