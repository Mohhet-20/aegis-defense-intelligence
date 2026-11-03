import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { scenarioApi } from '../api/scenarios'
import { useAuth } from '../context/auth'
import { CompareTab } from '../components/scenarios/CompareTab'
import { RunPanel } from '../components/scenarios/RunPanel'
import { MetricsTable, ParamEditor, SimBadge, SyntheticBanner } from '../components/scenarios/ScenarioBits'
import { downloadText, fmt, rangeText } from '../components/scenarios/scenarioUtils'
import { SensitivityTab } from '../components/scenarios/SensitivityTab'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { LoadState, Mono, Notice } from '../components/investigations/InvestigationBits'
import { errorText, fmtTime, useLoad } from '../components/investigations/useLoad'
import { Button, Card, EmptyState, PageHeader, StatusPill, Tabs } from '../components/ui/Primitives'
import type { MetricDoc, ParamValues, Scenario, SimulatorDoc } from '../types/scenario'

function Overview({ sc, sim, canWrite, onChanged }: { sc: Scenario; sim: SimulatorDoc; canWrite: boolean; onChanged: () => void }) {
  const nav = useNavigate()
  const versions = useLoad(() => scenarioApi.versions(sc.id), [sc.id, sc.updated_at])
  const [editing, setEditing] = useState(false)
  const [params, setParams] = useState<ParamValues>(sc.params)
  const [assumptions, setAssumptions] = useState(sc.assumptions.join('\n'))
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { setParams(sc.params); setAssumptions(sc.assumptions.join('\n')) }, [sc])

  async function save() {
    setError(null)
    try {
      await scenarioApi.update(sc.id, { params, assumptions: assumptions.split('\n').map((a) => a.trim()).filter(Boolean) })
      setEditing(false)
      onChanged()
    } catch (e) { setError(errorText(e, 'Could not save')) }
  }
  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-2 text-sm font-semibold text-slate-100">Purpose</h3>
        <p className="text-sm text-slate-300">{sc.question ?? 'No analytical question recorded.'}</p>
        {sc.description && <p className="mt-2 text-xs text-slate-400">{sc.description}</p>}
        <p className="mt-2 text-xs text-slate-500">Simulator: {sim.title} (<span className="font-mono">{sc.simulator_id}</span> v{sc.simulator_version}). Category: {sc.category}. Seed: {sc.seed}.{' '}
          {sc.execution_config.max_seconds ? `Time limit ${sc.execution_config.max_seconds}s.` : 'Default time limit applies.'}{' '}
          {sc.investigation_id && <>Context investigation: <Link className="text-accent-400 hover:underline" to={`/investigations/${sc.investigation_id}`}>open</Link> (context only; this scenario is not evidence in it).</>}
        </p>
      </Card>
      <Card>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-100">Input configuration and assumptions</h3>
          {canWrite && sc.status === 'draft' && !editing && <Button variant="secondary" onClick={() => setEditing(true)}>Edit draft</Button>}
        </div>
        {error && <Notice tone="warn">{error}</Notice>}
        {editing ? (
          <>
            <ParamEditor specs={sim.parameters} values={params} onChange={setParams} />
            <label className="mt-3 block text-xs font-medium text-slate-400">Assumptions (one per line)
              <textarea className="mt-1 w-full rounded-md border border-charcoal-600 bg-charcoal-900 px-3 py-1.5 text-sm text-slate-200" rows={4} value={assumptions} onChange={(e) => setAssumptions(e.target.value)} />
            </label>
            <div className="mt-3 flex gap-2"><Button onClick={save}>Save changes</Button><Button variant="secondary" onClick={() => { setEditing(false); setParams(sc.params) }}>Cancel</Button></div>
          </>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm"><caption className="sr-only">Scenario parameters</caption>
              <thead><tr className="text-xs uppercase text-slate-500"><th scope="col" className="py-1 pr-3">Parameter</th><th scope="col" className="pr-3">Value</th><th scope="col" className="pr-3">Allowed range</th><th scope="col">Description</th></tr></thead>
              <tbody>{sim.parameters.map((p) => (
                <tr key={p.name} className="border-t border-charcoal-700/60 align-top"><th scope="row" className="py-1 pr-3 font-mono text-xs font-normal">{p.name}</th><td className="pr-3">{fmt(sc.params[p.name])}{p.unit ? ` ${p.unit}` : ''}</td><td className="pr-3 text-xs text-slate-500">{rangeText(p)}</td><td className="text-xs text-slate-500">{p.description}</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <h4 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Assumptions (not measured facts)</h4>
        {sc.assumptions.length ? <ul className="list-disc pl-5 text-xs text-slate-400">{sc.assumptions.map((a) => <li key={a}>{a}</li>)}</ul> : <p className="text-xs text-status-warning">None recorded yet. Add at least one before marking the scenario ready.</p>}
        <h4 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Simulator assumptions</h4>
        <ul className="list-disc pl-5 text-xs text-slate-500">{sim.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        <h4 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Limitations</h4>
        <ul className="list-disc pl-5 text-xs text-slate-500">{sc.limitations.map((a) => <li key={a}>{a}</li>)}</ul>
      </Card>
      <Card>
        <h3 className="mb-2 text-sm font-semibold text-slate-100">Data origin</h3>
        <p className="text-xs text-slate-400">All inputs are <strong>synthetic</strong>, produced by the built-in generator from the seed and parameters above. No operational observation, event or evidence record is read or written by a simulation.</p>
      </Card>
      {sc.latest_summary && (
        <Card>
          <h3 className="mb-2 text-sm font-semibold text-slate-100">Latest completed simulation <SimBadge /></h3>
          <p className="mb-2 text-xs text-slate-500">Completed {fmtTime(sc.latest_summary.completed_at)}, seed {sc.latest_summary.seed}, run <Mono>{sc.latest_summary.run_id}</Mono></p>
          <MetricsTable metrics={sc.latest_summary.metrics} docs={sim.metrics} />
        </Card>
      )}
      <Card>
        <h3 className="mb-2 text-sm font-semibold text-slate-100">Version history</h3>
        <LoadState loading={versions.loading} error={versions.error}>
          <DataTable
            rows={versions.data ?? []}
            onRowClick={(v) => nav(`/scenarios/${v.id}`)}
            columns={[
              { header: 'Version', render: (v) => `v${v.version}${v.id === sc.id ? ' (this)' : ''}` },
              { header: 'Status', render: (v) => <StatusPill status={v.status} /> },
              { header: 'Title', render: (v) => v.title },
              { header: 'Created', render: (v) => fmtTime(v.created_at) },
              { header: 'Derived from', render: (v) => (v.parent_scenario_id ? <Mono>{v.parent_scenario_id.slice(0, 8)}</Mono> : 'original') },
            ]}
          />
        </LoadState>
      </Card>
    </div>
  )
}

function RunsTab({ sc, sim, canRun, selected, onSelect }: { sc: Scenario; sim: { metrics: MetricDoc[] }; canRun: boolean; selected: string | null; onSelect: (id: string | null) => void }) {
  const [page, setPage] = useState(1)
  const [nonce, setNonce] = useState(0)
  const runs = useLoad(() => scenarioApi.runs(sc.id, { page }), [sc.id, page, nonce])
  return (
    <div>
      <SyntheticBanner />
      <LoadState loading={runs.loading} error={runs.error}>
        {runs.data && runs.data.items.length === 0 ? <EmptyState message={sc.status === 'ready' ? 'No runs yet. Use "Run simulation" above.' : 'No runs. A scenario must be marked ready before it can run.'} /> : runs.data && (
          <>
            <DataTable
              rows={runs.data.items}
              onRowClick={(r) => onSelect(r.id)}
              columns={[
                { header: 'Started', render: (r) => fmtTime(r.started_at) },
                { header: 'Kind', render: (r) => r.run_kind },
                { header: 'Status', render: (r) => <StatusPill status={r.status} /> },
                { header: 'Seed', render: (r) => r.seed },
                { header: 'Runtime', render: (r) => (r.runtime_ms === null ? 'not recorded' : `${r.runtime_ms} ms`) },
                { header: 'Error', render: (r) => r.error_code ?? '' },
                { header: 'Run', render: (r) => <Mono>{r.id.slice(0, 8)}</Mono> },
              ]}
            />
            <Pagination page={runs.data.page} pageSize={runs.data.page_size} total={runs.data.total} onPageChange={setPage} />
          </>
        )}
      </LoadState>
      {selected && <RunPanel runId={selected} metricDocs={sim.metrics} canRun={canRun} onRetried={(r) => { setNonce((n) => n + 1); onSelect(r.id) }} />}
    </div>
  )
}

export function ScenarioDetailPage() {
  const { scenarioId = '' } = useParams()
  const { user } = useAuth()
  const nav = useNavigate()
  const canWrite = user?.role === 'administrator' || user?.role === 'analyst'
  const sc = useLoad(() => scenarioApi.get(scenarioId), [scenarioId])
  const sims = useLoad(() => scenarioApi.simulators(), [])
  const [tab, setTab] = useState('overview')
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { setSelectedRun(null); setTab('overview') }, [scenarioId])

  const sim = sims.data?.simulators.find((s) => s.id === sc.data?.simulator_id)

  async function act(fn: () => Promise<unknown>, after?: () => void) {
    setBusy(true)
    setError(null)
    try { await fn(); sc.reload(); after?.() } catch (e) { setError(errorText(e, 'Action failed')) } finally { setBusy(false) }
  }
  async function exportAs(format: 'json' | 'markdown') {
    try {
      const { text, filename } = await scenarioApi.exportText(scenarioId, format)
      downloadText(filename, text, format === 'json' ? 'application/json' : 'text/markdown')
    } catch (e) { setError(errorText(e, 'Export failed')) }
  }

  return (
    <LoadState loading={sc.loading || sims.loading} error={sc.error || sims.error}>
      {sc.data && sim && (() => {
        const s = sc.data
        return (
          <div>
            <PageHeader
              title={`${s.title}`}
              description={<span>Version {s.version} <StatusPill status={s.status} /> <SimBadge /> - <Link className="text-accent-400 hover:underline" to="/scenarios">all scenarios</Link></span>}
              actions={
                <div className="flex flex-wrap justify-end gap-2">
                  {canWrite && s.status === 'draft' && <Button disabled={busy} onClick={() => act(() => scenarioApi.markReady(s.id))}>Mark ready (assumptions reviewed)</Button>}
                  {canWrite && s.status === 'ready' && <Button disabled={busy} onClick={async () => { setBusy(true); setError(null); try { const r = await scenarioApi.run(s.id); sc.reload(); setTab('runs'); setSelectedRun(r.id) } catch (e) { setError(errorText(e, 'Run failed to start')) } finally { setBusy(false) } }}>{busy ? 'Running...' : 'Run simulation'}</Button>}
                  {canWrite && s.status !== 'archived' && <Button variant="secondary" disabled={busy} onClick={() => act(async () => { const n = await scenarioApi.duplicate(s.id); nav(`/scenarios/${n.id}`) })}>New version (duplicate)</Button>}
                  {canWrite && s.status !== 'archived' && <Button variant="secondary" disabled={busy} onClick={() => act(() => scenarioApi.archive(s.id))}>Archive</Button>}
                  <Button variant="secondary" onClick={() => exportAs('markdown')}>Export Markdown</Button>
                  <Button variant="secondary" onClick={() => exportAs('json')}>Export JSON</Button>
                </div>
              }
            />
            <SyntheticBanner />
            {error && <Notice tone="warn">{error}</Notice>}
            {s.status === 'ready' && <Notice>This version is ready and its configuration can no longer be edited. To change a parameter, create a new version.</Notice>}
            <Tabs
              tabs={[{ key: 'overview', label: 'Overview' }, { key: 'runs', label: 'Runs' }, { key: 'compare', label: 'Compare' }, { key: 'sensitivity', label: 'Sensitivity' }]}
              active={tab} onChange={setTab}
            />
            {tab === 'overview' && <Overview sc={s} sim={sim} canWrite={canWrite} onChanged={sc.reload} />}
            {tab === 'runs' && <RunsTab sc={s} sim={sim} canRun={canWrite} selected={selectedRun} onSelect={setSelectedRun} />}
            {tab === 'compare' && <CompareTab scenario={s} />}
            {tab === 'sensitivity' && <SensitivityTab scenario={s} sim={sim} canRun={canWrite} />}
          </div>
        )
      })()}
    </LoadState>
  )
}
