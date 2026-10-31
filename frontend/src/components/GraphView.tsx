import { useQuery } from '@tanstack/react-query'
import { Info, LoaderCircle, Maximize2, Network, Sparkles, X } from 'lucide-react'
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from 'react-force-graph-2d'
import { api } from '../api'
import { colorFor } from '../format'
import type { AnswerContext, GraphMeta, GraphNode, GraphPayload } from '../types'

export type GraphMode = 'answer' | 'full'

interface LinkData {
  id: string
  type: string
  properties: Record<string, unknown>
}
type FNode = NodeObject<GraphNode>
type FLink = LinkObject<GraphNode, LinkData>

interface Props {
  mode: GraphMode
  onModeChange: (mode: GraphMode) => void
  answer: AnswerContext | null
  meta: GraphMeta | undefined
  documentId: string | null
  onDocumentChange: (id: string | null) => void
  refreshKey: string
}

const endId = (end: FLink['source']) => (typeof end === 'object' && end ? String(end.id) : String(end))

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  useEffect(() => {
    if (!ref.current) return
    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: Math.floor(entry.contentRect.width), height: Math.floor(entry.contentRect.height) })
    })
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])
  return [ref, size] as const
}

/** Copies the payload: force-graph mutates nodes and links in place. */
function toGraphData(payload: GraphPayload | undefined) {
  const nodes: FNode[] = (payload?.nodes ?? []).map((n) => ({ ...n }))
  const ids = new Set(nodes.map((n) => n.id))
  const links: FLink[] = (payload?.links ?? [])
    .filter((l) => ids.has(l.source) && ids.has(l.target))
    .map((l) => ({ ...l }))
  return { nodes, links }
}

export function GraphView({ mode, onModeChange, answer, meta, documentId, onDocumentChange, refreshKey }: Props) {
  const [types, setTypes] = useState<string[]>([])
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [containerRef, size] = useSize<HTMLDivElement>()
  const fgRef = useRef<ForceGraphMethods<FNode, FLink> | undefined>(undefined)

  const full = useQuery({
    queryKey: ['graph', documentId, types, refreshKey],
    queryFn: () => api.graph({ documentId: documentId ?? undefined, types }),
    enabled: mode === 'full',
  })

  const payload = mode === 'answer' ? answer?.graph : full.data
  const data = useMemo(() => toGraphData(payload), [payload])
  const highlight = useMemo(
    () => (mode === 'full' && answer ? new Set(answer.graph.nodes.map((n) => n.id)) : null),
    [mode, answer],
  )
  const rankedLabels = useMemo(() => meta?.entity_types.map((t) => t.label) ?? [], [meta])
  const legend = useMemo(() => {
    const counts = new Map<string, number>()
    for (const n of data.nodes) counts.set(n.label, (counts.get(n.label) ?? 0) + 1)
    return [...counts.entries()].sort((a, b) => b[1] - a[1])
  }, [data])

  useEffect(() => setSelected(null), [mode, answer, documentId])

  const isDim = (id: string) => highlight !== null && highlight.size > 0 && !highlight.has(id)
  const fit = () => fgRef.current?.zoomToFit(400, 40)
  const toggleType = (label: string) =>
    setTypes((t) => (t.includes(label) ? t.filter((x) => x !== label) : [...t, label]))

  const drawNode = (node: FNode, ctx: CanvasRenderingContext2D, scale: number) => {
    const r = 4 + Math.min(6, Math.sqrt(node.degree ?? 1))
    const dim = isDim(node.id)
    const color = colorFor(node.label, rankedLabels)
    ctx.globalAlpha = dim ? 0.15 : 1
    ctx.beginPath()
    ctx.arc(node.x ?? 0, node.y ?? 0, r, 0, 2 * Math.PI)
    ctx.fillStyle = color
    ctx.fill()
    if (selected?.id === node.id || (highlight?.has(node.id) ?? false)) {
      ctx.lineWidth = 2 / scale
      ctx.strokeStyle = '#111827'
      ctx.stroke()
    }
    if (scale > 1.2 || data.nodes.length < 40 || highlight?.has(node.id)) {
      const fontSize = Math.max(10 / scale, 2)
      ctx.font = `${fontSize}px Inter, system-ui, sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      ctx.fillStyle = '#1f2937'
      const label = node.name.length > 32 ? `${node.name.slice(0, 30)}…` : node.name
      ctx.fillText(label, node.x ?? 0, (node.y ?? 0) + r + 1)
    }
    ctx.globalAlpha = 1
  }

  const linkDim = (l: FLink) => highlight !== null && (isDim(endId(l.source)) || isDim(endId(l.target)))

  let body: ReactNode
  if (mode === 'answer' && !answer) {
    body = (
      <div className="empty">
        <Sparkles size={28} />
        <p>Ask a question to see the part of the knowledge graph used to answer it.</p>
        <button className="btn" onClick={() => onModeChange('full')}>
          <Network size={14} /> Browse the full graph
        </button>
      </div>
    )
  } else if (mode === 'full' && full.isLoading) {
    body = (
      <div className="empty">
        <LoaderCircle size={24} className="spin" />
      </div>
    )
  } else if (mode === 'full' && full.error) {
    body = <div className="empty error">{(full.error as Error).message}</div>
  } else if (data.nodes.length === 0) {
    body = (
      <div className="empty">
        <Network size={28} />
        <p>
          {mode === 'answer'
            ? 'No graph entities were linked to the passages used for this answer.'
            : 'The knowledge graph is empty. Upload a PDF to get started.'}
        </p>
      </div>
    )
  } else {
    body = (
      <ForceGraph2D<GraphNode, LinkData>
        ref={fgRef}
        width={size.width}
        height={size.height}
        graphData={data}
        nodeId="id"
        nodeLabel={(n) => `${n.name} (${n.label})`}
        nodeCanvasObject={drawNode}
        nodePointerAreaPaint={(node, color, ctx) => {
          ctx.fillStyle = color
          ctx.beginPath()
          ctx.arc(node.x ?? 0, node.y ?? 0, 9, 0, 2 * Math.PI)
          ctx.fill()
        }}
        linkLabel={(l) => l.type}
        linkColor={(l) => (linkDim(l) ? 'rgba(148,163,184,0.12)' : 'rgba(100,116,139,0.55)')}
        linkWidth={(l) => (highlight && !linkDim(l) ? 1.8 : 1)}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        cooldownTicks={120}
        onEngineStop={fit}
        onNodeClick={(n) => setSelected(n)}
        onBackgroundClick={() => setSelected(null)}
      />
    )
  }

  const neighbours = selected
    ? data.links
        .filter((l) => endId(l.source) === selected.id || endId(l.target) === selected.id)
        .slice(0, 30)
        .map((l) => {
          const out = endId(l.source) === selected.id
          const otherId = out ? endId(l.target) : endId(l.source)
          const other = data.nodes.find((n) => n.id === otherId)
          return { id: l.id, out, type: l.type, name: other?.name ?? '?' }
        })
    : []
  const docName = (id: string) => meta?.documents.find((d) => d.id === id)?.file_name ?? id

  return (
    <section className="panel graph-panel">
      <header className="panel-header graph-header">
        <div className="tabs">
          <button className={mode === 'answer' ? 'active' : ''} onClick={() => onModeChange('answer')}>
            <Sparkles size={14} /> Answer subgraph
          </button>
          <button className={mode === 'full' ? 'active' : ''} onClick={() => onModeChange('full')}>
            <Network size={14} /> Full graph
          </button>
        </div>
        {mode === 'full' && (
          <select value={documentId ?? ''} onChange={(e) => onDocumentChange(e.target.value || null)}>
            <option value="">All documents</option>
            {meta?.documents.map((d) => (
              <option key={d.id} value={d.id}>
                {d.file_name}
              </option>
            ))}
          </select>
        )}
        <button className="icon-btn" onClick={fit} title="Fit to view" disabled={data.nodes.length === 0}>
          <Maximize2 size={16} />
        </button>
      </header>

      {mode === 'answer' && answer && (
        <div className="graph-caption" title={answer.question}>
          For: “{answer.question}”
        </div>
      )}
      {mode === 'full' && meta && meta.entity_types.length > 0 && (
        <div className="type-filter">
          {meta.entity_types.slice(0, 16).map((t) => (
            <button
              key={t.label}
              className={`chip${types.includes(t.label) ? ' on' : ''}`}
              onClick={() => toggleType(t.label)}
            >
              <span className="swatch" style={{ background: colorFor(t.label, rankedLabels) }} />
              {t.label} <span className="muted">{t.count}</span>
            </button>
          ))}
          {types.length > 0 && (
            <button className="chip" onClick={() => setTypes([])}>
              Clear
            </button>
          )}
        </div>
      )}

      <div className="graph-canvas" ref={containerRef}>
        {body}

        {legend.length > 0 && (
          <div className="legend">
            {legend.slice(0, 10).map(([label, count]) => (
              <div key={label}>
                <span className="swatch" style={{ background: colorFor(label, rankedLabels) }} />
                {label} <span className="muted">{count}</span>
              </div>
            ))}
          </div>
        )}

        {mode === 'full' && full.data?.truncated && (
          <div className="graph-note">
            <Info size={12} /> Showing the {full.data.nodes.length} most connected of {full.data.total_nodes} entities. Use
            the filters to narrow down.
          </div>
        )}
        {highlight && highlight.size > 0 && (
          <div className="graph-note top">
            <Sparkles size={12} /> Highlighting entities used for the selected answer
          </div>
        )}

        {selected && (
          <aside className="node-details">
            <header>
              <div>
                <span className="swatch" style={{ background: colorFor(selected.label, rankedLabels) }} />
                <strong>{selected.name}</strong>
              </div>
              <button className="icon-btn" onClick={() => setSelected(null)} aria-label="Close">
                <X size={14} />
              </button>
            </header>
            <div className="muted small">{selected.label}</div>
            <dl>
              {Object.entries(selected.properties)
                .filter(([k]) => k !== 'name')
                .map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
                  </div>
                ))}
            </dl>
            {selected.documents && selected.documents.length > 0 && (
              <>
                <h4>Mentioned in</h4>
                <ul>
                  {selected.documents.map((d) => (
                    <li key={d}>{docName(d)}</li>
                  ))}
                </ul>
              </>
            )}
            {neighbours.length > 0 && (
              <>
                <h4>Relationships</h4>
                <ul className="rels">
                  {neighbours.map((n) => (
                    <li key={n.id}>
                      {n.out ? '→' : '←'} <code>{n.type}</code> {n.name}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </aside>
        )}
      </div>
    </section>
  )
}
