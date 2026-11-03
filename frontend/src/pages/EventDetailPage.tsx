import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/auth'
import type { AegisEvent, Evidence, EventCorrelation, EvidenceRelationship, RawRecord } from '../types/api'
import { Button, Card, DataOriginBadge, ErrorState, PageHeader, Spinner, StatusPill } from '../components/ui/Primitives'

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between border-b border-charcoal-700/50 py-2 text-sm last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  )
}

export function EventDetailPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const { eventId } = useParams<{ eventId: string }>()
  const [event, setEvent] = useState<AegisEvent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [rawRecord, setRawRecord] = useState<RawRecord | null>(null)
  const [rawRecordError, setRawRecordError] = useState<string | null>(null)
  const [correlations, setCorrelations] = useState<EventCorrelation[] | null>(null)
  const [relationships, setRelationships] = useState<EvidenceRelationship[] | null>(null)
  const [evidence, setEvidence] = useState<Evidence[] | null>(null)

  const canSeeProvenance = user?.role === 'administrator' || user?.role === 'analyst' || user?.role === 'investigator'

  useEffect(() => {
    if (!eventId) return
    api.events
      .get(eventId)
      .then(setEvent)
      .catch((e) => setError(e.message))
  }, [eventId])

  useEffect(() => {
    if (!eventId || !canSeeProvenance) return
    api.events.correlations(eventId).then(setCorrelations).catch(() => setCorrelations([]))
    api.relationships
      .list({ ref_type: 'event', ref_id: eventId, page_size: 50 })
      .then((d) => setRelationships(d.items))
      .catch(() => setRelationships([]))
    api.evidence
      .list({ event_id: eventId, page_size: 50 })
      .then((d) => setEvidence(d.items))
      .catch(() => setEvidence([]))
  }, [eventId, canSeeProvenance])

  // Only events created by file ingestion link a raw record; asking for one
  // otherwise is a guaranteed 404, so read the link from the event first.
  const rawRecordId = event?.provenance?.raw_record_id
  useEffect(() => {
    if (!event || !canSeeProvenance) return
    if (!rawRecordId) {
      setRawRecordError(
        event.data_origin === 'synthetic_demo'
          ? 'No linked raw record: this is a synthetic demo event created by the seed script, not by ingestion.'
          : 'No linked raw record: this event was not created by file ingestion.',
      )
      return
    }
    api.events
      .rawRecord(event.id)
      .then(setRawRecord)
      .catch((e) => setRawRecordError(e instanceof ApiError && e.status === 404 ? 'The linked raw record is no longer available.' : e.message))
  }, [event, rawRecordId, canSeeProvenance])

  if (error) return <ErrorState message={error} />
  if (!event) return <Spinner />

  return (
    <div>
      <PageHeader
        title={event.title}
        description={
          <>
            <Link to="/events" className="text-accent-400 hover:underline">
              Event Explorer
            </Link>{' '}
            / {event.id}
          </>
        }
        actions={
          <div className="flex items-center gap-2">
            <DataOriginBadge origin={event.data_origin} />
            {canSeeProvenance && (
              <Button variant="secondary" onClick={() => navigate(`/fusion/graph?seed_type=event&seed_id=${event.id}`)}>
                View in evidence graph
              </Button>
            )}
          </div>
        }
      />

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Classification &amp; triage</h2>
          <Row label="Event type" value={event.event_type} />
          <Row label="Source severity (source's own scale)" value={event.source_severity ?? '--'} />
          <Row label="Priority (this platform's triage)" value={event.priority ? <StatusPill status={event.priority} /> : '--'} />
          <Row label="Confidence" value={event.confidence !== null ? event.confidence.toFixed(2) : 'not set -- no real basis yet'} />
          <Row label="Processing status" value={<StatusPill status={event.processing_status} />} />
          <Row label="Classification" value={event.classification} />
        </Card>

        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Provenance &amp; timing</h2>
          <Row label="Source ID" value={<span className="font-mono text-xs">{event.source_id}</span>} />
          <Row label="External ID" value={event.external_id ?? '-- (deduped by content hash)'} />
          <Row label="Observed at" value={new Date(event.observed_at).toLocaleString()} />
          <Row label="Ingested at" value={new Date(event.ingested_at).toLocaleString()} />
          <Row label="Ingestion job" value={event.ingestion_job_id ? <span className="font-mono text-xs">{event.ingestion_job_id}</span> : '--'} />
          <Row
            label="Coordinates"
            value={event.latitude !== null && event.longitude !== null ? `${event.latitude.toFixed(4)}, ${event.longitude.toFixed(4)}` : 'not provided'}
          />
        </Card>

        <Card className="md:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Description</h2>
          <p className="text-sm text-slate-300">{event.description ?? 'No description provided.'}</p>
        </Card>

        <Card className="md:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-slate-200">Raw attributes</h2>
          <pre className="overflow-x-auto rounded-md bg-navy-950 p-3 text-xs text-slate-400">
            {JSON.stringify(event.attributes, null, 2)}
          </pre>
        </Card>

        {canSeeProvenance && (
          <Card className="md:col-span-2">
            <h2 className="mb-2 text-sm font-semibold text-slate-200">Provenance (raw record)</h2>
            {rawRecordError && <p className="text-sm text-slate-500">{rawRecordError}</p>}
            {!rawRecordError && !rawRecord && <Spinner />}
            {rawRecord && (
              <>
                <Row label="Connector" value={`${rawRecord.connector_type} v${rawRecord.connector_version}`} />
                <Row label="Normalization / schema version" value={`${rawRecord.normalization_version} / ${rawRecord.schema_version}`} />
                <Row label="Content fingerprint" value={<span className="font-mono text-xs">{rawRecord.content_fingerprint}</span>} />
                <Row label="Validation status" value={<StatusPill status={rawRecord.validation_status} />} />
                {rawRecord.validation_warnings.length > 0 && (
                  <Row
                    label="Validation warnings"
                    value={<span className="text-xs text-status-warning">{rawRecord.validation_warnings.map((w) => w.code).join(', ')}</span>}
                  />
                )}
                <h3 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Original payload</h3>
                <pre className="overflow-x-auto rounded-md bg-navy-950 p-3 text-xs text-slate-400">
                  {JSON.stringify(rawRecord.payload, null, 2)}
                </pre>
              </>
            )}
          </Card>
        )}

        {canSeeProvenance && evidence && evidence.length > 0 && (
          <Card className="md:col-span-2">
            <h2 className="mb-2 text-sm font-semibold text-slate-200">Evidence pointing at this event</h2>
            <ul className="space-y-1 text-sm">
              {evidence.map((item) => (
                <li key={item.id} className="flex items-center justify-between border-b border-charcoal-700/50 py-2 last:border-0">
                  <span className="text-slate-300">{item.title}</span>
                  <span className="text-xs text-slate-500">{item.evidence_type}</span>
                </li>
              ))}
            </ul>
          </Card>
        )}

        {canSeeProvenance && relationships && relationships.length > 0 && (
          <Card className="md:col-span-2">
            <h2 className="mb-2 text-sm font-semibold text-slate-200">Evidence relationships</h2>
            <p className="mb-2 text-xs text-slate-500">
              Analyst-drawn or rule-generated links to other events/evidence -- distinct from the rule-based correlations below, and never
              auto-confirmed.
            </p>
            <ul className="space-y-2">
              {relationships.map((r) => {
                const sourceIsThis = r.source_event_id === event.id
                const otherType = sourceIsThis ? (r.target_event_id ? 'event' : 'evidence') : r.source_event_id ? 'event' : 'evidence'
                const otherId = sourceIsThis ? r.target_event_id ?? r.target_evidence_id : r.source_event_id ?? r.source_evidence_id
                return (
                  <li key={r.id} className="flex items-center justify-between border-b border-charcoal-700/50 py-2 text-sm last:border-0">
                    <div>
                      <span className="text-xs text-slate-500">{r.relationship_type}</span>{' '}
                      {otherType === 'event' && otherId ? (
                        <Link to={`/events/${otherId}`} className="font-mono text-xs text-accent-400 hover:underline">
                          {otherId}
                        </Link>
                      ) : (
                        <span className="font-mono text-xs text-slate-400">{otherId}</span>
                      )}
                    </div>
                    <StatusPill status={r.review_status} />
                  </li>
                )
              })}
            </ul>
          </Card>
        )}

        {canSeeProvenance && correlations && correlations.length > 0 && (
          <Card className="md:col-span-2">
            <h2 className="mb-2 text-sm font-semibold text-slate-200">Correlated candidates</h2>
            <p className="mb-2 text-xs text-slate-500">
              A transparent rule-based grouping for analyst review -- never an assertion that these events are confirmed related.
            </p>
            <ul className="space-y-2">
              {correlations.map((c) => {
                const otherId = c.event_a_id === event.id ? c.event_b_id : c.event_a_id
                return (
                  <li key={c.id} className="flex items-center justify-between border-b border-charcoal-700/50 py-2 text-sm last:border-0">
                    <Link to={`/events/${otherId}`} className="font-mono text-xs text-accent-400 hover:underline">
                      {otherId}
                    </Link>
                    <span className="text-xs text-slate-400">{c.reasons.join(', ')}</span>
                    <StatusPill status={c.review_status} />
                  </li>
                )
              })}
            </ul>
          </Card>
        )}
      </div>
    </div>
  )
}
