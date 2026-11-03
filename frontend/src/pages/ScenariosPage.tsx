import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { scenarioApi } from '../api/scenarios'
import { useAuth } from '../context/auth'
import { ParamEditor, SimBadge, SyntheticBanner } from '../components/scenarios/ScenarioBits'
import { DataTable } from '../components/tables/DataTable'
import { Pagination } from '../components/tables/DataTable'
import { LoadState, Notice } from '../components/investigations/InvestigationBits'
import { errorText, fmtTime, useLoad } from '../components/investigations/useLoad'
import { Button, Card, EmptyState, Field, PageHeader, StatusPill, inputClass } from '../components/ui/Primitives'
import type { ParamValues, Scenario, ScenarioStatus, ValidateResult } from '../types/scenario'

function Builder({ onCreated, onCancel }: { onCreated: (s: Scenario) => void; onCancel: () => void }) {
  const sims = useLoad(() => scenarioApi.simulators(), [])
  const tpls = useLoad(() => scenarioApi.templates(), [])
  const [templateId, setTemplateId] = useState('')
  const [simId, setSimId] = useState('')
  const [title, setTitle] = useState('')
  const [question, setQuestion] = useState('')
  const [assumptions, setAssumptions] = useState('')
  const [seed, setSeed] = useState(1)
  const [params, setParams] = useState<ParamValues>({})
  const [validation, setValidation] = useState<ValidateResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const sim = useMemo(() => sims.data?.simulators.find((s) => s.id === simId), [sims.data, simId])
  const tpl = useMemo(() => tpls.data?.templates.find((t) => t.id === templateId), [tpls.data, templateId])

  useEffect(() => {
    if (!sim) return
    const base: ParamValues = {}
    for (const p of sim.parameters) if (p.default !== null) base[p.name] = p.default
    setParams({ ...base, ...(tpl && tpl.simulator_id === sim.id ? tpl.params : {}) })
    setValidation(null)
  }, [sim, tpl])

  function pickTemplate(id: string) {
    setTemplateId(id)
    const t = tpls.data?.templates.find((x) => x.id === id)
    if (t) {
      setSimId(t.simulator_id)
      setTitle((cur) => cur || t.title)
      setQuestion(t.question)
      setAssumptions(t.assumptions.join('\n'))
    }
  }

  async function validate() {
    if (!sim) return
    setError(null)
    try { setValidation(await scenarioApi.validate(sim.id, params)) } catch (e) { setError(errorText(e, 'Validation failed')) }
  }

  async function save() {
    if (!sim) return
    setBusy(true)
    setError(null)
    try {
      const created = await scenarioApi.create({
        title, question: question || undefined, template_id: templateId || undefined, simulator_id: sim.id, params, seed,
        assumptions: assumptions.split('\n').map((a) => a.trim()).filter(Boolean),
      })
      onCreated(created)
    } catch (e) {
      setError(errorText(e, 'Could not save the draft'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="mb-6">
      <h2 className="mb-3 text-sm font-semibold text-slate-100">New scenario (saved as a draft; nothing runs until you mark it ready and start a run)</h2>
      <LoadState loading={sims.loading || tpls.loading} error={sims.error || tpls.error}>
        {error && <Notice tone="warn">{error}</Notice>}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Start from a template">
            <select className={inputClass} value={templateId} onChange={(e) => pickTemplate(e.target.value)}>
              <option value="">(none - choose a simulator)</option>
              {tpls.data?.templates.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </select>
          </Field>
          <Field label="Simulator (registered methods only)">
            <select className={inputClass} value={simId} onChange={(e) => { setSimId(e.target.value); setTemplateId('') }}>
              <option value="">Select a simulator</option>
              {sims.data?.simulators.map((s) => <option key={s.id} value={s.id}>{s.title} (v{s.version})</option>)}
            </select>
          </Field>
          <Field label="Title"><input className={inputClass} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Random seed (same seed + same settings = same result)"><input className={inputClass} type="number" min={0} max={2147483647} value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></Field>
        </div>
        <div className="mt-3"><Field label="Analytical question"><input className={inputClass} value={question} maxLength={1000} onChange={(e) => setQuestion(e.target.value)} /></Field></div>
        {sim && (
          <>
            <p className="mt-3 text-xs text-slate-400">{sim.description}</p>
            <h3 className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Parameters</h3>
            <ParamEditor specs={sim.parameters} values={params} onChange={(v) => { setParams(v); setValidation(null) }} />
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <Field label="Assumptions (one per line; review them - a scenario cannot be marked ready without at least one)">
                  <textarea className={inputClass} rows={5} value={assumptions} onChange={(e) => setAssumptions(e.target.value)} />
                </Field>
                <p className="mt-1 text-[11px] text-slate-500">Simulator assumptions built into the method:</p>
                <ul className="list-disc pl-5 text-[11px] text-slate-500">{sim.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
              </div>
              <div>
                <h4 className="mb-1 text-xs font-medium text-slate-400">Known limitations of this simulator (saved with the scenario)</h4>
                <ul className="list-disc pl-5 text-[11px] text-slate-500">{sim.limitations.map((a) => <li key={a}>{a}</li>)}</ul>
              </div>
            </div>
          </>
        )}
        {validation && (
          validation.valid
            ? <Notice>Configuration is valid.</Notice>
            : <Notice tone="warn">Not valid: {validation.errors.map((e) => `${e.param}: ${e.message}`).join('; ')}</Notice>
        )}
        <div className="mt-4 flex gap-2">
          <Button variant="secondary" disabled={!sim} onClick={validate}>Validate</Button>
          <Button disabled={!sim || !title.trim() || busy} onClick={save}>{busy ? 'Saving...' : 'Save draft'}</Button>
          <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        </div>
      </LoadState>
    </Card>
  )
}

export function ScenariosPage() {
  const { user } = useAuth()
  const nav = useNavigate()
  const canWrite = user?.role === 'administrator' || user?.role === 'analyst'
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<ScenarioStatus | ''>('')
  const [q, setQ] = useState('')
  const [latestOnly, setLatestOnly] = useState(true)
  const [building, setBuilding] = useState(false)
  const list = useLoad(() => scenarioApi.list({ page, status, q, latestOnly }), [page, status, q, latestOnly])

  return (
    <div>
      <PageHeader
        title="Scenario Simulation"
        description="Define hypothetical, bounded simulations on synthetic data; compare alternatives and inspect sensitivity. Results are simulated, never evidence."
        actions={canWrite ? <Button onClick={() => setBuilding(true)}>New scenario</Button> : undefined}
      />
      <SyntheticBanner />
      {building && canWrite && <Builder onCancel={() => setBuilding(false)} onCreated={(s) => nav(`/scenarios/${s.id}`)} />}
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <Field label="Search title"><input className={inputClass} value={q} maxLength={100} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></Field>
        <Field label="Status">
          <select className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value as ScenarioStatus | ''); setPage(1) }}>
            <option value="">All</option><option value="draft">Draft</option><option value="ready">Ready</option><option value="archived">Archived</option>
          </select>
        </Field>
        <label className="flex items-center gap-2 pb-2 text-xs text-slate-400">
          <input type="checkbox" checked={latestOnly} onChange={(e) => { setLatestOnly(e.target.checked); setPage(1) }} /> Latest version of each scenario only
        </label>
      </div>
      <LoadState loading={list.loading} error={list.error}>
        {list.data && list.data.items.length === 0 ? (
          <EmptyState message={canWrite ? 'No scenarios yet. Create one from a template to get started.' : 'No scenarios are available to you yet.'} />
        ) : list.data && (
          <>
            <DataTable
              rows={list.data.items}
              onRowClick={(s) => nav(`/scenarios/${s.id}`)}
              columns={[
                { header: 'Scenario', render: (s) => <span className="text-slate-100">{s.title} <SimBadge /></span> },
                { header: 'Version', render: (s) => `v${s.version}` },
                { header: 'Status', render: (s) => <StatusPill status={s.status} /> },
                { header: 'Simulator', render: (s) => `${s.simulator_id} v${s.simulator_version}` },
                { header: 'Latest run', render: (s) => (s.latest_summary ? fmtTime(s.latest_summary.completed_at) : 'No completed run') },
                { header: 'Updated', render: (s) => fmtTime(s.updated_at) },
              ]}
            />
            <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onPageChange={setPage} />
          </>
        )}
      </LoadState>
    </div>
  )
}
