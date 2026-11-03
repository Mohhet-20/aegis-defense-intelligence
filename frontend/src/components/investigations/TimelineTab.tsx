import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { TimelineEntry } from '../../types/workspace'
import { Button, Card, EmptyState, Field, inputClass } from '../ui/Primitives'
import { Pagination } from '../tables/DataTable'
import { LoadState, Mono, Notice } from './InvestigationBits'
import { fmtTime, useLoad } from './useLoad'

const TYPES = ['event', 'observation', 'media_asset', 'assessment', 'evidence', 'detection_result', 'track', 'note', 'investigation', 'ingestion_job', 'inference_job']
const KINDS = ['event_time', 'observation_time', 'capture_time', 'registration_time', 'ingestion_time', 'processing_time', 'review_time', 'association_time', 'integrity_check_time', 'note_time', 'status_change']

function recordLink(e: TimelineEntry): string | null {
  switch (e.record_type) {
    case 'event': return `/events/${e.record_id}`
    case 'assessment': return `/assessments/${e.record_id}`
    default: return null
  }
}

export function TimelineTab({ investigationId }: { investigationId: string }) {
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [types, setTypes] = useState<string[]>([])
  const [kind, setKind] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<TimelineEntry | null>(null)

  const { data, error, loading } = useLoad(
    () =>
      api.workspace.timeline(investigationId, {
        page,
        page_size: 25,
        start: start ? new Date(start).toISOString() : undefined,
        end: end ? new Date(end).toISOString() : undefined,
        record_type: types.length ? types : undefined,
        time_kind: kind ? [kind] : undefined,
      }),
    [investigationId, page, start, end, types, kind],
  )

  return (
    <div className="space-y-3">
      <Notice>
        {data?.notice ?? 'Entries are ordered by recorded time only. Closeness in time does not show that one record caused or explains another.'}{' '}
        {data?.timestamp_semantics}
      </Notice>
      <Card>
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="From (local)"><input type="datetime-local" className={inputClass} value={start} onChange={(e) => { setStart(e.target.value); setPage(1) }} /></Field>
          <Field label="To (local)"><input type="datetime-local" className={inputClass} value={end} onChange={(e) => { setEnd(e.target.value); setPage(1) }} /></Field>
          <Field label="Record type">
            <select multiple className={`${inputClass} h-24`} value={types} onChange={(e) => { setTypes(Array.from(e.target.selectedOptions, (o) => o.value)); setPage(1) }}>
              {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Kind of time">
            <select className={inputClass} value={kind} onChange={(e) => { setKind(e.target.value); setPage(1) }}>
              <option value="">All</option>
              {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </Field>
        </div>
        <p className="mt-2 text-xs text-slate-500">A date range matches only entries that have a recorded time; entries with unknown times are hidden while a range is set.</p>
      </Card>

      <LoadState loading={loading} error={error}>
        {data && data.items.length === 0 && <EmptyState message="No timeline entries match. Link records or evidence to this investigation to build a timeline." />}
        {data && data.items.length > 0 && (
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              {data.unknown_time_entries > 0 && <Notice tone="warn">{data.unknown_time_entries} entries have no recorded time; they are listed last.</Notice>}
              <ol className="space-y-2">
                {data.items.map((e) => (
                  <li key={e.entry_id}>
                    <button type="button" onClick={() => setSelected(e)} className={`w-full rounded-md border px-3 py-2 text-left text-sm ${selected?.entry_id === e.entry_id ? 'border-accent-500 bg-charcoal-800' : 'border-charcoal-700 hover:bg-charcoal-800/60'}`}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`font-mono text-xs ${e.time_known ? 'text-slate-300' : 'text-status-warning'}`}>{e.time_known ? fmtTime(e.timestamp) : 'time unknown'}</span>
                        <span className="rounded-sm bg-charcoal-700 px-1.5 py-0.5 text-[11px] text-slate-300">{e.time_kind}</span>
                        <span className="text-[11px] text-slate-500">{e.record_type}</span>
                        {e.assumed_utc && <span className="text-[11px] text-slate-500" title="Stored without an offset; read as UTC">assumed UTC</span>}
                      </div>
                      <div className="mt-1 text-slate-200">{e.title}</div>
                      {!e.time_known && e.missing_time_note && <div className="text-xs text-status-warning">{e.missing_time_note}</div>}
                    </button>
                  </li>
                ))}
              </ol>
              <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
              {data.truncated && <Notice tone="warn">The timeline was truncated at the server limit.</Notice>}
            </Card>
            <Card>
              <h3 className="mb-2 text-sm font-semibold text-slate-200">Entry details</h3>
              {!selected ? <p className="text-sm text-slate-500">Select an entry to see its record and provenance details.</p> : (
                <dl className="space-y-2 text-sm">
                  <div><dt className="text-xs text-slate-500">Record</dt><dd>{selected.record_type} <Mono>{selected.record_id}</Mono></dd></div>
                  <div><dt className="text-xs text-slate-500">Time ({selected.time_kind})</dt><dd>{fmtTime(selected.timestamp)}</dd></div>
                  <div><dt className="text-xs text-slate-500">Original timezone</dt><dd>{selected.original_timezone ?? 'Not retained'}</dd></div>
                  <div><dt className="text-xs text-slate-500">Source</dt><dd>{selected.source_id ? <Mono>{selected.source_id}</Mono> : 'Unknown'}</dd></div>
                  <div><dt className="text-xs text-slate-500">Details</dt><dd><pre className="overflow-auto rounded-sm bg-charcoal-900 p-2 text-xs text-slate-300">{JSON.stringify(selected.details, null, 2)}</pre></dd></div>
                  {recordLink(selected) && <Link className="text-accent-400 hover:underline" to={recordLink(selected) as string}>Open record</Link>}
                </dl>
              )}
              {selected && <Button variant="secondary" onClick={() => setSelected(null)}>Clear</Button>}
            </Card>
          </div>
        )}
      </LoadState>
    </div>
  )
}
