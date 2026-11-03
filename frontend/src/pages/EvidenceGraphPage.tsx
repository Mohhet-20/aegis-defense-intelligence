import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { GraphResponse } from '../types/api'
import { Button, Card, ErrorState, Field, PageHeader, StatusPill, inputClass } from '../components/ui/Primitives'

const NODE_COLOR: Record<string, string> = {
  event: '#38bdf8', // accent blue
  evidence: '#a78bfa', // violet
  assessment: '#34d399', // green
}

const EDGE_COLOR: Record<string, string> = {
  correlation: '#64748b',
  relationship: '#38bdf8',
  conflict: '#f87171',
  assessment_link: '#34d399',
}

function layoutNodes(graph: GraphResponse, width: number, height: number) {
  const cx = width / 2
  const cy = height / 2
  const seedKey = `${graph.seed.type}:${graph.seed.id}`
  const others = graph.nodes.filter((n) => `${n.type}:${n.id}` !== seedKey)
  const radius = Math.min(cx, cy) - 60
  const positions = new Map<string, { x: number; y: number }>()
  positions.set(seedKey, { x: cx, y: cy })
  others.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(others.length, 1)
    positions.set(`${n.type}:${n.id}`, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) })
  })
  return positions
}

export function EvidenceGraphPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [seedType, setSeedType] = useState(searchParams.get('seed_type') ?? 'event')
  const [seedId, setSeedId] = useState(searchParams.get('seed_id') ?? '')
  const [reviewStatus, setReviewStatus] = useState('')
  const [graph, setGraph] = useState<GraphResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function runQuery(type: string, id: string, status: string) {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const result = await api.fusion.graph({ seed_type: type, seed_id: id, review_status: status || undefined })
      setGraph(result)
    } catch (err) {
      setGraph(null)
      setError(err instanceof ApiError ? err.message : 'Could not build the graph.')
    } finally {
      setLoading(false)
    }
  }

  // Arriving here from a link that already names a seed (e.g. "View in
  // evidence graph" on an event) builds the graph immediately -- the
  // analyst shouldn't have to re-type the ID they just clicked.
  useEffect(() => {
    const t = searchParams.get('seed_type')
    const i = searchParams.get('seed_id')
    if (t && i) runQuery(t, i, '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    runQuery(seedType, seedId, reviewStatus)
  }

  const width = 760
  const height = 520
  const positions = graph ? layoutNodes(graph, width, height) : null

  return (
    <div>
      <PageHeader
        title="Evidence Graph Explorer"
        description="A bounded breadth-first traversal from one seed node -- never the whole dataset. Depth and node-count caps are always enforced server-side, no matter what is requested here; a truncated traversal says so explicitly."
      />

      <Card className="mb-5 max-w-2xl">
        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
          <Field label="Seed type">
            <select className={inputClass} value={seedType} onChange={(e) => setSeedType(e.target.value)}>
              <option value="event">event</option>
              <option value="evidence">evidence</option>
              <option value="assessment">assessment</option>
            </select>
          </Field>
          <Field label="Seed ID">
            <input className={inputClass} value={seedId} onChange={(e) => setSeedId(e.target.value)} required placeholder="event / evidence / assessment id" />
          </Field>
          <Field label="Only show edges reviewed as">
            <select className={inputClass} value={reviewStatus} onChange={(e) => setReviewStatus(e.target.value)}>
              <option value="">any</option>
              <option value="confirmed">confirmed</option>
              <option value="candidate">candidate</option>
              <option value="rejected">rejected</option>
              <option value="uncertain">uncertain</option>
            </select>
          </Field>
          <Button type="submit">{loading ? 'Building…' : 'Build graph'}</Button>
        </form>
      </Card>

      {error && <ErrorState message={error} />}

      {graph && (
        <>
          {graph.truncated && (
            <div className="mb-4 rounded-md border border-status-warning/30 bg-status-warning/10 px-4 py-2.5 text-sm text-status-warning">
              This traversal hit the node cap ({graph.max_nodes} nodes, depth {graph.max_depth}) and was truncated -- it is a partial view, not the complete
              neighborhood.
            </div>
          )}

          <Card className="mb-5 overflow-x-auto">
            <svg width={width} height={height} role="img" aria-label="Evidence graph visualization (see the accessible table below for the same data)">
              <rect x={0} y={0} width={width} height={height} fill="transparent" />
              {positions &&
                graph.edges.map((edge) => {
                  const a = positions.get(`${edge.source.type}:${edge.source.id}`)
                  const b = positions.get(`${edge.target.type}:${edge.target.id}`)
                  if (!a || !b) return null
                  return (
                    <line
                      key={edge.id}
                      x1={a.x}
                      y1={a.y}
                      x2={b.x}
                      y2={b.y}
                      stroke={EDGE_COLOR[edge.type] ?? '#64748b'}
                      strokeWidth={2}
                      strokeDasharray={edge.type === 'relationship' && edge.review_status === 'candidate' ? '4 3' : undefined}
                      opacity={0.75}
                    />
                  )
                })}
              {positions &&
                graph.nodes.map((node) => {
                  const pos = positions.get(`${node.type}:${node.id}`)
                  if (!pos) return null
                  const isSeed = node.type === graph.seed.type && node.id === graph.seed.id
                  return (
                    <g key={`${node.type}:${node.id}`} transform={`translate(${pos.x}, ${pos.y})`} className="cursor-pointer" onClick={() => node.type === 'event' && navigate(`/events/${node.id}`)}>
                      <circle r={isSeed ? 14 : 9} fill={NODE_COLOR[node.type] ?? '#94a3b8'} stroke={isSeed ? '#fff' : 'none'} strokeWidth={2} />
                      <text y={isSeed ? 28 : 22} textAnchor="middle" fontSize={11} fill="#cbd5e1">
                        {node.label.length > 18 ? `${node.label.slice(0, 18)}…` : node.label}
                      </text>
                    </g>
                  )
                })}
            </svg>
            <div className="mt-3 flex gap-4 text-xs text-slate-500">
              {Object.entries(NODE_COLOR).map(([type, color]) => (
                <span key={type} className="flex items-center gap-1.5">
                  <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
                  {type}
                </span>
              ))}
            </div>
          </Card>

          <Card>
            <h2 className="mb-3 text-sm font-semibold text-slate-200">Accessible data view</h2>
            <p className="mb-3 text-xs text-slate-500">The same graph as a table -- for screen readers, keyboard navigation, or anyone who prefers data to a picture.</p>

            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Nodes ({graph.nodes.length})</h3>
            <table className="mb-4 w-full text-left text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-slate-500">
                  <th className="py-1 pr-3">Type</th>
                  <th className="py-1 pr-3">ID</th>
                  <th className="py-1">Label</th>
                </tr>
              </thead>
              <tbody>
                {graph.nodes.map((n) => (
                  <tr key={`${n.type}:${n.id}`} className="border-t border-charcoal-700/50">
                    <td className="py-1 pr-3 text-slate-400">{n.type}</td>
                    <td className="py-1 pr-3 font-mono text-xs text-slate-400">{n.id}</td>
                    <td className="py-1 text-slate-300">{n.label}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Edges ({graph.edges.length})</h3>
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-slate-500">
                  <th className="py-1 pr-3">Type</th>
                  <th className="py-1 pr-3">Source</th>
                  <th className="py-1 pr-3">Target</th>
                  <th className="py-1 pr-3">Status</th>
                  <th className="py-1">Why</th>
                </tr>
              </thead>
              <tbody>
                {graph.edges.map((e) => (
                  <tr key={e.id} className="border-t border-charcoal-700/50">
                    <td className="py-1 pr-3 text-slate-400">{e.type}</td>
                    <td className="py-1 pr-3 font-mono text-xs text-slate-400">{e.source.type}:{e.source.id.slice(0, 8)}</td>
                    <td className="py-1 pr-3 font-mono text-xs text-slate-400">{e.target.type}:{e.target.id.slice(0, 8)}</td>
                    <td className="py-1 pr-3">{e.review_status ? <StatusPill status={e.review_status} /> : '--'}</td>
                    <td className="py-1 text-xs text-slate-400">
                      {e.reasons?.join(', ') ?? e.relationship_type ?? e.role ?? (e.conflicting_fields ? `${e.conflicting_fields.length} conflicting field(s)` : '--')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  )
}
