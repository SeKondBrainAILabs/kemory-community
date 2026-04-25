/**
 * Memory Vault — Access Graph Page (F12-US-003 + F12-US-004)
 *
 * Interactive force-directed graph showing:
 *   - Agent nodes (which agents exist)
 *   - Namespace nodes (which namespaces exist)
 *   - Memory nodes (L1/L2/L3.1 — colour coded)
 *   - Edges: agent→namespace (writes_to / reads_from)
 *            memory→namespace (in_namespace)
 *            concept→source (synthesized_from)
 *
 * Clicking a node opens the inspection side panel (F12-US-004).
 *
 * Stories: F12-US-003, F12-US-004
 */
import { useRef, useCallback, useState, useEffect } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { PageShell } from '@/components/layout/PageShell'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { MemoryLevelBadge } from '@/components/shared/MemoryLevelBadge'
import { useAccessMap } from '@/hooks/useMemories'
import type { GraphNode, GraphEdge } from '@/api/types'
import { X, RefreshCw, Bot, FolderOpen, Database } from 'lucide-react'

// ── Colour palette ──────────────────────────────────────────────────────────

const NODE_COLORS: Record<string, string> = {
  agent: '#6366f1',       // indigo
  namespace: '#0ea5e9',   // sky
  memory_L1: '#94a3b8',   // slate
  memory_L2: '#3b82f6',   // blue
  'memory_L3.1': '#8b5cf6', // violet
}

const EDGE_COLORS: Record<string, string> = {
  writes_to: '#6366f1',
  reads_from: '#0ea5e9',
  in_namespace: '#94a3b8',
  synthesized_from: '#8b5cf6',
}

// ── Graph data transforms ───────────────────────────────────────────────────

interface FGNode extends GraphNode {
  x?: number
  y?: number
  vx?: number
  vy?: number
  fx?: number
  fy?: number
  __color?: string
}

interface FGLink {
  source: string | FGNode
  target: string | FGNode
  relation: string
  color: string
}

function buildGraphData(nodes: GraphNode[], edges: GraphEdge[]) {
  const fgNodes: FGNode[] = nodes.map((n) => ({
    ...n,
    __color: n.type === 'memory'
      ? NODE_COLORS[`memory_${n.compression_tier ?? 'L1'}`] ?? NODE_COLORS.memory_L1
      : NODE_COLORS[n.type] ?? '#64748b',
  }))

  const fgLinks: FGLink[] = edges.map((e) => ({
    source: e.source,
    target: e.target,
    relation: e.relation,
    color: EDGE_COLORS[e.relation] ?? '#94a3b8',
  }))

  return { nodes: fgNodes, links: fgLinks }
}

// ── Node icon helpers ────────────────────────────────────────────────────────

function NodeIcon({ type }: { type: string }) {
  if (type === 'agent') return <Bot size={14} className="shrink-0 text-indigo-500" />
  if (type === 'namespace') return <FolderOpen size={14} className="shrink-0 text-sky-500" />
  return <Database size={14} className="shrink-0 text-slate-400" />
}

// ── Legend ───────────────────────────────────────────────────────────────────

function GraphLegend() {
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-lg border border-border bg-white px-4 py-2 text-xs text-content-secondary shadow-sm">
      <span className="font-semibold text-content-primary">Legend</span>
      {[
        { color: NODE_COLORS.agent, label: 'Agent' },
        { color: NODE_COLORS.namespace, label: 'Namespace' },
        { color: NODE_COLORS.memory_L1, label: 'L1 Memory' },
        { color: NODE_COLORS.memory_L2, label: 'L2 Memory' },
        { color: NODE_COLORS['memory_L3.1'], label: 'L3.1 Concept' },
      ].map(({ color, label }) => (
        <span key={label} className="flex items-center gap-1.5">
          <span
            className="inline-block h-3 w-3 rounded-full"
            style={{ backgroundColor: color }}
          />
          {label}
        </span>
      ))}
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export function AccessGraphPage() {
  const { data, isLoading, isError, refetch, isFetching } = useAccessMap()
  const [selectedNode, setSelectedNode] = useState<FGNode | null>(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 })
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<any>(null)

  // Resize observer to fill available space
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const obs = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        })
      }
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  const graphData = data ? buildGraphData(data.nodes, data.edges) : { nodes: [], links: [] }

  const handleNodeClick = useCallback((node: object) => {
    setSelectedNode(node as FGNode)
  }, [])

  const handleBackgroundClick = useCallback(() => {
    setSelectedNode(null)
  }, [])

  const paintNode = useCallback((node: object, ctx: CanvasRenderingContext2D) => {
    const n = node as FGNode
    const r = n.type === 'namespace' ? 8 : n.type === 'agent' ? 7 : 5
    ctx.beginPath()
    ctx.arc(n.x ?? 0, n.y ?? 0, r, 0, 2 * Math.PI)
    ctx.fillStyle = n.__color ?? '#64748b'
    ctx.fill()

    // Label
    ctx.font = '4px sans-serif'
    ctx.fillStyle = '#1e293b'
    ctx.textAlign = 'center'
    ctx.fillText(n.label, n.x ?? 0, (n.y ?? 0) + r + 5)
  }, [])

  return (
    <PageShell>
      {/* Header row */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-content-primary">Access Graph</h1>
          <p className="text-xs text-content-tertiary">
            Agent → Namespace → Memory relationships across all compression levels
          </p>
        </div>
        <div className="flex items-center gap-3">
          {data && (
            <div className="flex items-center gap-3 text-xs text-content-tertiary">
              <span><span className="font-semibold text-content-primary">{data.total_agents}</span> agents</span>
              <span><span className="font-semibold text-content-primary">{data.total_namespaces}</span> namespaces</span>
              <span><span className="font-semibold text-content-primary">{data.total_memories}</span> memories</span>
            </div>
          )}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-1.5 rounded-lg border border-border bg-white px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
          >
            <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      <GraphLegend />

      {/* Graph + side panel */}
      <div className="mt-3 flex gap-4" style={{ height: 'calc(100vh - 220px)' }}>
        {/* Graph canvas */}
        <div
          ref={containerRef}
          className="relative min-w-0 flex-1 overflow-hidden rounded-lg border border-border bg-slate-50"
        >
          {isLoading ? (
            <div className="flex h-full items-center justify-center">
              <LoadingSkeleton lines={8} />
            </div>
          ) : isError ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-content-tertiary">
              <p>Failed to load graph data.</p>
              <button
                onClick={() => refetch()}
                className="rounded-lg border border-border bg-white px-3 py-1.5 text-xs hover:bg-surface-secondary"
              >
                Retry
              </button>
            </div>
          ) : graphData.nodes.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-content-tertiary">
              <p>No graph data yet. Create some memories to see the graph.</p>
            </div>
          ) : (
            <ForceGraph2D
              ref={graphRef}
              graphData={graphData}
              width={dimensions.width}
              height={dimensions.height}
              nodeCanvasObject={paintNode}
              nodeCanvasObjectMode={() => 'replace'}
              linkColor={(link: object) => (link as FGLink).color}
              linkWidth={1.2}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={1}
              onNodeClick={handleNodeClick}
              onBackgroundClick={handleBackgroundClick}
              cooldownTicks={120}
              nodeId="id"
            />
          )}
        </div>

        {/* F12-US-004: Node inspection side panel */}
        {selectedNode && (
          <div className="w-80 shrink-0 overflow-y-auto rounded-lg border border-border bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <NodeIcon type={selectedNode.type} />
                <h3 className="text-sm font-semibold text-content-primary capitalize">
                  {selectedNode.type} Detail
                </h3>
              </div>
              <button
                onClick={() => setSelectedNode(null)}
                className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary"
              >
                <X size={14} />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <div className="mb-0.5 text-content-tertiary">Label</div>
                <div className="font-semibold text-content-primary">{selectedNode.label}</div>
              </div>

              <div>
                <div className="mb-0.5 text-content-tertiary">ID</div>
                <code className="block break-all rounded bg-surface-tertiary px-2 py-1 text-content-primary">
                  {selectedNode.id}
                </code>
              </div>

              {selectedNode.type === 'memory' && selectedNode.compression_tier && (
                <div>
                  <div className="mb-1 text-content-tertiary">Compression Level</div>
                  <MemoryLevelBadge tier={selectedNode.compression_tier} />
                </div>
              )}

              {selectedNode.namespace && (
                <div>
                  <div className="mb-0.5 text-content-tertiary">Namespace</div>
                  <div className="font-medium text-content-primary">{selectedNode.namespace}</div>
                </div>
              )}

              {selectedNode.status && (
                <div>
                  <div className="mb-0.5 text-content-tertiary">Status</div>
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                    selectedNode.status === 'active'
                      ? 'bg-green-50 text-green-700'
                      : selectedNode.status === 'inactive'
                        ? 'bg-slate-50 text-slate-600'
                        : 'bg-amber-50 text-amber-700'
                  }`}>
                    {selectedNode.status}
                  </span>
                </div>
              )}

              {/* Agent-specific stats */}
              {selectedNode.type === 'agent' && (
                <div className="rounded-lg bg-surface-secondary p-3">
                  <div className="mb-2 text-xs font-semibold text-content-secondary">Activity</div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <div className="text-content-tertiary">Writes</div>
                      <div className="font-semibold text-content-primary">
                        {selectedNode.total_writes ?? 0}
                      </div>
                    </div>
                    <div>
                      <div className="text-content-tertiary">Reads</div>
                      <div className="font-semibold text-content-primary">
                        {selectedNode.total_reads ?? 0}
                      </div>
                    </div>
                    <div>
                      <div className="text-content-tertiary">Denied</div>
                      <div className="font-semibold text-status-danger">
                        {selectedNode.denied_requests ?? 0}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Namespace-specific stats */}
              {selectedNode.type === 'namespace' && (
                <div className="rounded-lg bg-surface-secondary p-3">
                  <div className="mb-2 text-xs font-semibold text-content-secondary">Contents</div>
                  <div>
                    <div className="text-content-tertiary">Memory count</div>
                    <div className="font-semibold text-content-primary">
                      {selectedNode.memory_count ?? 0}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </PageShell>
  )
}
