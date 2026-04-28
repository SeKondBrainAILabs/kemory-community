/**
 * Memory Vault — Memory Explorer Page
 *
 * EPIC-002 fixes:
 *   KMV-QA-013: Add Delete Memory button with confirmation dialog
 *   KMV-QA-014: Add Edit Memory inline form in the detail panel
 *   KMV-QA-015: Add pagination controls (offset-based, 50 per page)
 *
 * KMV-E12 (Multi-Level Memory Reads):
 *   KMV-S12.1: Memory Level Toggle UI (Raw / Compress / Compacted / Cognition)
 *   KMV-S12.2: Raw and AAAK (Compress) views
 *   KMV-S12.3: Compacted (Concept) and Cognition views
 */
import { useState } from 'react'
import { type ColumnDef } from '@tanstack/react-table'
import { PageShell } from '@/components/layout/PageShell'
import { DataTable } from '@/components/shared/DataTable'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { SearchInput } from '@/components/shared/SearchInput'
import { JsonViewer } from '@/components/shared/JsonViewer'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import {
  useMemorySearch,
  useNamespaces,
  useMemoryEnrichment,
  useDeleteMemory,
  useUpdateMemory,
  useMemoryLevel,
} from '@/hooks/useMemories'
import { formatRelativeTime } from '@/lib/utils'
import { cn } from '@/lib/utils'
import type { MemoryResponse } from '@/api/types'
import type { MemoryReadMode } from '@/api/memories'
import { X, Trash2, Pencil, ChevronLeft, ChevronRight, Check, Layers } from 'lucide-react'
import { NamespaceSummaryHeader } from '@/components/memories/NamespaceSummaryHeader'
import { MemoryHealthBadge } from '@/components/memories/MemoryHealthBadge'
import { MemoryLevelsSection } from '@/components/memories/MemoryLevelsSection'
import { SessionSummarySection } from '@/components/memories/SessionSummarySection'
import { MemoryLevelBadge, MemoryLevelLegend } from '@/components/shared/MemoryLevelBadge'

const PAGE_SIZE = 50

const contentTypes = ['all', 'text', 'structured', 'conversation', 'fact', 'preference'] as const

// F12: Compression tier filter — L1 raw / L2 AAAK / L3.1 concept
const tiers = ['all', 'L1', 'L2', 'L3.1'] as const
type TierFilter = (typeof tiers)[number]

// KMV-S12.1: Memory level definitions
const MEMORY_LEVELS: { mode: MemoryReadMode; label: string; description: string }[] = [
  { mode: 'raw',       label: 'Raw (L1)',      description: 'Every active memory as raw dicts' },
  { mode: 'aaak',      label: 'Compress (L2)', description: 'Lossless AAAK encoding with compression metrics' },
  { mode: 'concept',   label: 'Compacted (L3)', description: 'LLM-synthesized concepts' },
  { mode: 'cognition', label: 'Cognition (L4)', description: 'Concepts + Cognition OS graph entities' },
]

const columns: ColumnDef<MemoryResponse, unknown>[] = [
  {
    accessorKey: 'content',
    header: 'Content',
    cell: ({ getValue }) => (
      <span className="line-clamp-2 max-w-sm text-sm">{getValue() as string}</span>
    ),
  },
  { accessorKey: 'namespace', header: 'Namespace' },
  {
    accessorKey: 'content_type',
    header: 'Type',
    cell: ({ getValue }) => (
      <span className="rounded bg-surface-tertiary px-2 py-0.5 text-xs">{getValue() as string}</span>
    ),
  },
  {
    // F12: Compression tier (L1 raw / L2 AAAK / L3.1 concept)
    accessorKey: 'compression_tier',
    header: 'Tier',
    cell: ({ getValue }) => <MemoryLevelBadge tier={(getValue() as string) ?? 'L1'} />,
  },
  {
    // KMV-S15.3: Per-row memory health (status pill, weight bar, archive countdown)
    id: 'health',
    header: 'Health',
    cell: ({ row }) => {
      const m = row.original as MemoryResponse & {
        weight?: number | null
        consolidation_status?: string | null
      }
      return (
        <MemoryHealthBadge
          weight={m.weight ?? null}
          consolidationStatus={m.consolidation_status ?? null}
          createdAt={m.created_at}
          compact
        />
      )
    },
  },
  {
    accessorKey: 'enrichment_status',
    header: 'Enrichment',
    cell: ({ getValue }) => <StatusBadge status={getValue() as string} />,
  },
  { accessorKey: 'version', header: 'Ver' },
  {
    accessorKey: 'created_at',
    header: 'Created',
    cell: ({ getValue }) => formatRelativeTime(getValue() as string),
  },
]

// ── KMV-S12.2: Raw View ──────────────────────────────────────────────────────
function MemoryRawView({ namespace }: { namespace: string }) {
  const { data, isLoading, isError } = useMemoryLevel(namespace, 'raw')
  if (isLoading) return <LoadingSkeleton lines={6} />
  if (isError) return <p className="text-xs text-status-danger">Failed to load raw memories.</p>
  if (!data) return null
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-content-tertiary">
        <span className="rounded bg-surface-tertiary px-2 py-0.5 font-mono">
          {data.source_count} {data.source_count === 1 ? 'memory' : 'memories'}
        </span>
        <span>source: {data.source}</span>
      </div>
      <JsonViewer data={data.memories ?? []} />
    </div>
  )
}

// ── KMV-S12.2: AAAK (Compress) View ─────────────────────────────────────────
function MemoryAaakView({ namespace }: { namespace: string }) {
  const { data, isLoading, isError } = useMemoryLevel(namespace, 'aaak')
  if (isLoading) return <LoadingSkeleton lines={4} />
  if (isError) return <p className="text-xs text-status-danger">Failed to load AAAK encoding.</p>
  if (!data) return null
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-xs">
        <div className="rounded bg-surface-tertiary px-3 py-1.5">
          <span className="text-content-tertiary">Source count: </span>
          <span className="font-semibold">{data.source_count}</span>
        </div>
        <div className="rounded bg-surface-tertiary px-3 py-1.5">
          <span className="text-content-tertiary">Compressed size: </span>
          <span className="font-semibold">{data.compressed_size ?? '—'} bytes</span>
        </div>
        <div className="rounded bg-brand-primary/10 px-3 py-1.5 text-brand-primary">
          <span className="font-semibold">{data.ratio != null ? `${data.ratio}×` : '—'}</span>
          <span className="ml-1 text-content-tertiary">compression</span>
        </div>
      </div>
      <pre className="overflow-x-auto rounded-lg border border-border bg-surface-tertiary p-3 text-xs font-mono whitespace-pre-wrap">
        {data.content ?? '(empty)'}
      </pre>
    </div>
  )
}

// ── KMV-S12.3: Concept (Compacted) View ──────────────────────────────────────
function MemoryConceptView({ namespace }: { namespace: string }) {
  const { data, isLoading, isError } = useMemoryLevel(namespace, 'concept')
  if (isLoading) return <LoadingSkeleton lines={5} />
  if (isError) return <p className="text-xs text-status-danger">Failed to load concept synthesis.</p>
  if (!data) return null
  const concepts = data.concepts ?? []
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs text-content-tertiary">
        <span className="rounded bg-surface-tertiary px-2 py-0.5">
          {data.source_count} source {data.source_count === 1 ? 'memory' : 'memories'}
        </span>
        <span>→ {concepts.length} {concepts.length === 1 ? 'concept' : 'concepts'}</span>
        <span className="rounded bg-surface-tertiary px-2 py-0.5">source: {data.source}</span>
      </div>
      {concepts.length === 0 ? (
        <p className="text-xs text-content-tertiary italic">No concepts synthesized yet.</p>
      ) : (
        <div className="space-y-2">
          {concepts.map((c, i) => (
              <div key={i} className="rounded-lg border border-border bg-white p-3">
                <div className="mb-1 flex items-center gap-2">
                  <span className="text-xs font-semibold text-content-primary">
                    {String((c as Record<string, unknown>).name ?? `Concept ${i + 1}`)}
                  </span>
                  {Boolean((c as Record<string, unknown>).directional) && (
                    <span className="rounded bg-brand-primary/10 px-1.5 py-0.5 text-xs text-brand-primary">directional</span>
                  )}
                  {Boolean((c as Record<string, unknown>).synthesis_unavailable) && (
                    <span className="rounded bg-status-warning/10 px-1.5 py-0.5 text-xs text-status-warning">synthesis unavailable</span>
                  )}
                </div>
                <p className="text-xs text-content-secondary">
                  {String((c as Record<string, unknown>).synthesis ?? '—')}
                </p>
              </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── KMV-S12.3: Cognition (L4) View ───────────────────────────────────────────
function MemoryCognitionView({ namespace }: { namespace: string }) {
  const { data, isLoading, isError } = useMemoryLevel(namespace, 'cognition')
  if (isLoading) return <LoadingSkeleton lines={6} />
  if (isError) return <p className="text-xs text-status-danger">Failed to load cognition synthesis.</p>
  if (!data) return null
  const concepts = data.concepts ?? []
  const graphEntities = data.graph_entities ?? []
  const cogAvailable = data.cognition_os_available ?? false
  return (
    <div className="space-y-4">
      {/* Status bar */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded bg-surface-tertiary px-2 py-0.5 text-content-tertiary">
          {data.source_count} source {data.source_count === 1 ? 'memory' : 'memories'}
        </span>
        <span className={cn(
          'rounded px-2 py-0.5 font-medium',
          cogAvailable
            ? 'bg-status-success/10 text-status-success'
            : 'bg-surface-tertiary text-content-tertiary',
        )}>
          Cognition OS: {cogAvailable ? 'connected' : 'unavailable'}
        </span>
        <span className="text-content-tertiary">source: {data.source}</span>
      </div>

      {/* Synthesized Concepts */}
      <div>
        <h4 className="mb-2 text-xs font-semibold text-content-secondary uppercase tracking-wide">
          Synthesized Concepts ({concepts.length})
        </h4>
        {concepts.length === 0 ? (
          <p className="text-xs text-content-tertiary italic">No concepts synthesized yet.</p>
        ) : (
          <div className="space-y-2">
            {concepts.map((c, i) => (
              <div key={i} className="rounded-lg border border-border bg-white p-3">
                <div className="mb-1 flex items-center gap-2">
                  <span className="text-xs font-semibold text-content-primary">
                    {String((c as Record<string, unknown>).name ?? `Concept ${i + 1}`)}
                  </span>
                  {Boolean((c as Record<string, unknown>).directional) && (
                    <span className="rounded bg-brand-primary/10 px-1.5 py-0.5 text-xs text-brand-primary">directional</span>
                  )}
                </div>
                <p className="text-xs text-content-secondary">
                  {String((c as Record<string, unknown>).synthesis ?? '—')}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Cognition OS Graph Entities */}
      <div>
        <h4 className="mb-2 text-xs font-semibold text-content-secondary uppercase tracking-wide">
          Cognition OS Graph Entities ({graphEntities.length})
        </h4>
        {!cogAvailable ? (
          <p className="text-xs text-content-tertiary italic">
            Cognition OS is not connected. Configure it in the Connectors page to enable L4 graph augmentation.
          </p>
        ) : graphEntities.length === 0 ? (
          <p className="text-xs text-content-tertiary italic">No related graph entities found.</p>
        ) : (
          <div className="space-y-2">
            {graphEntities.map((e, i) => (
              <div key={i} className="rounded-lg border border-border bg-surface-secondary p-3">
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs font-semibold text-content-primary">{e.title}</span>
                  <span className="rounded bg-brand-primary/10 px-1.5 py-0.5 text-xs text-brand-primary">
                    {(e.score * 100).toFixed(0)}% match
                  </span>
                </div>
                <p className="line-clamp-2 text-xs text-content-secondary">{e.content}</p>
                <div className="mt-1 text-xs text-content-tertiary font-mono">{e.entity_id}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export function MemoryExplorerPage() {
  const [query, setQuery] = useState('')
  const [namespace, setNamespace] = useState<string>('')
  const [contentType, setContentType] = useState('all')
  const [tier, setTier] = useState<TierFilter>('all')
  const [selected, setSelected] = useState<MemoryResponse | null>(null)
  const [page, setPage] = useState(0)

  // KMV-S12.1: Memory level toggle state
  const [memoryLevel, setMemoryLevel] = useState<MemoryReadMode>('raw')
  const [showLevelView, setShowLevelView] = useState(false)

  // Edit state
  const [editing, setEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [editContentType, setEditContentType] = useState('')

  // Namespace search filter (for large namespace lists)
  const [nsFilter, setNsFilter] = useState('')

  // Delete confirm dialog
  const [confirmDelete, setConfirmDelete] = useState(false)

  const namespaces = useNamespaces()
  const search = useMemorySearch({
    query: query || undefined,
    namespace: namespace || undefined,
    content_type: contentType === 'all' ? undefined : contentType,
    compression_tier: tier === 'all' ? undefined : tier,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    // Hybrid mode tolerates an empty query (falls back to a plain SQL
    // listing) whereas fts mode returns 422. Keeps the Explorer populated
    // on first open, before the user has typed anything.
    search_mode: 'hybrid',
  })

  const enrichment = useMemoryEnrichment(selected?.memory_id ?? '')
  const deleteMutation = useDeleteMemory()
  const updateMutation = useUpdateMemory()

  const totalCount = search.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))

  function openDetail(row: MemoryResponse) {
    setSelected(row)
    setEditing(false)
    setEditContent(row.content)
    setEditContentType(row.content_type)
  }

  function handleDelete() {
    if (!selected) return
    deleteMutation.mutate(selected.memory_id, {
      onSuccess: () => {
        setSelected(null)
        setConfirmDelete(false)
      },
    })
  }

  function handleSaveEdit() {
    if (!selected) return
    updateMutation.mutate(
      {
        memoryId: selected.memory_id,
        data: {
          content: editContent,
          content_type: editContentType || undefined,
        },
      },
      {
        onSuccess: (updated) => {
          setSelected(updated)
          setEditing(false)
        },
      },
    )
  }

  return (
    <PageShell>
      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SearchInput
          value={query}
          onChange={(v) => { setQuery(v); setPage(0) }}
          placeholder="Search memories…"
          className="w-64"
        />
        {/* Namespace selector — includes text filter when list is large */}
        <div className="flex flex-col gap-1">
          {(namespaces.data?.length ?? 0) > 10 && (
            <input
              type="text"
              value={nsFilter}
              onChange={(e) => setNsFilter(e.target.value)}
              placeholder="Filter namespaces…"
              className="rounded-lg border border-border bg-white px-3 py-1.5 text-xs text-content-primary focus:border-brand-primary focus:outline-none"
            />
          )}
          <select
            value={namespace}
            onChange={(e) => { setNamespace(e.target.value); setPage(0) }}
            className="rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none"
          >
            <option value="">
              All namespaces ({namespaces.data?.reduce((s, n) => s + n.count, 0) ?? 0})
            </option>
            {namespaces.data
              ?.filter((ns) =>
                nsFilter === '' ||
                ns.namespace.toLowerCase().includes(nsFilter.toLowerCase())
              )
              .map((ns) => (
                <option key={ns.namespace} value={ns.namespace}>
                  {ns.namespace} ({ns.count})
                </option>
              ))}
          </select>
        </div>
        <div className="flex gap-1">
          {contentTypes.map((ct) => (
            <button
              key={ct}
              onClick={() => { setContentType(ct); setPage(0) }}
              className={cn(
                'rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors',
                contentType === ct
                  ? 'bg-brand-primary text-white'
                  : 'border border-border bg-white text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {ct}
            </button>
          ))}
        </div>

        {/* F12: Compression tier filter pills (L1 / L2 / L3.1) */}
        <div className="flex items-center gap-1" title="Filter by memory compression tier">
          {tiers.map((t) => (
            <button
              key={t}
              onClick={() => { setTier(t); setPage(0) }}
              className={cn(
                'rounded-full px-3 py-1 text-xs font-medium transition-colors',
                tier === t
                  ? 'bg-brand-primary text-white'
                  : 'border border-border bg-white text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {t === 'all' ? 'All tiers' : t}
            </button>
          ))}
        </div>

        {/* KMV-S12.1: Memory Level View toggle button */}
        {namespace && (
          <button
            onClick={() => setShowLevelView((v) => !v)}
            className={cn(
              'ml-auto flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
              showLevelView
                ? 'border-brand-primary bg-brand-primary text-white'
                : 'border-border bg-white text-content-secondary hover:bg-surface-secondary',
            )}
            title="View memory levels for selected namespace"
          >
            <Layers size={13} />
            Memory Levels
          </button>
        )}
      </div>

      {/* F12: Tier legend — explains what L1 / L2 / L3.1 mean */}
      <div className="mb-3 px-1">
        <MemoryLevelLegend />
      </div>

      {/* KMV-S12.1/12.2/12.3: Memory Level View Panel */}
      {showLevelView && namespace && (
        <div className="mb-4 rounded-xl border border-border bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Layers size={15} className="text-brand-primary" />
              <h3 className="text-sm font-semibold text-content-primary">
                Memory Levels — <span className="font-mono text-brand-primary">{namespace}</span>
              </h3>
            </div>
            <button
              onClick={() => setShowLevelView(false)}
              className="rounded p-1 text-content-tertiary hover:bg-surface-secondary"
            >
              <X size={14} />
            </button>
          </div>

          {/* Level selector tabs */}
          <div className="mb-4 flex gap-1 rounded-lg border border-border bg-surface-secondary p-1">
            {MEMORY_LEVELS.map(({ mode, label, description }) => (
              <button
                key={mode}
                onClick={() => setMemoryLevel(mode)}
                title={description}
                className={cn(
                  'flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                  memoryLevel === mode
                    ? 'bg-white text-brand-primary shadow-sm'
                    : 'text-content-secondary hover:text-content-primary',
                )}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Level description */}
          <p className="mb-3 text-xs text-content-tertiary">
            {MEMORY_LEVELS.find((l) => l.mode === memoryLevel)?.description}
          </p>

          {/* Level content — KMV-S12.2 and KMV-S12.3 */}
          <div className="max-h-[480px] overflow-y-auto">
            {memoryLevel === 'raw'       && <MemoryRawView namespace={namespace} />}
            {memoryLevel === 'aaak'      && <MemoryAaakView namespace={namespace} />}
            {memoryLevel === 'concept'   && <MemoryConceptView namespace={namespace} />}
            {memoryLevel === 'cognition' && <MemoryCognitionView namespace={namespace} />}
          </div>
        </div>
      )}

      <div className="flex gap-4">
        {/* Table */}
        <div className="min-w-0 flex-1 space-y-3">
          {/* KMV-S15.2: Namespace summary header (counts + decay policy + manual sync) */}
          {namespace && (
            <NamespaceSummaryHeader
              namespace={namespace}
              totalMemories={totalCount}
            />
          )}

          {search.isLoading ? (
            <LoadingSkeleton lines={10} />
          ) : (
            <>
              <DataTable
                columns={columns}
                data={search.data?.items ?? []}
                onRowClick={openDetail}
              />
              {/* Pagination — KMV-QA-015 */}
              <div className="mt-3 flex items-center justify-between text-xs text-content-tertiary">
                <span>
                  {totalCount} {totalCount === 1 ? 'memory' : 'memories'} total
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={page === 0}
                    className="rounded p-1 hover:bg-surface-secondary disabled:opacity-40"
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <span>Page {page + 1} of {totalPages}</span>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                    disabled={page >= totalPages - 1}
                    className="rounded p-1 hover:bg-surface-secondary disabled:opacity-40"
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Detail panel */}
        {selected && (
          <div className="w-96 shrink-0 rounded-lg border border-border bg-white p-4">
            {/* Panel header */}
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-content-primary">Memory Detail</h3>
              <div className="flex items-center gap-1">
                {!editing && (
                  <button
                    onClick={() => setEditing(true)}
                    className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-brand-primary"
                    title="Edit memory"
                  >
                    <Pencil size={14} />
                  </button>
                )}
                <button
                  onClick={() => setConfirmDelete(true)}
                  className="rounded p-1.5 text-content-tertiary hover:bg-red-50 hover:text-status-danger"
                  title="Delete memory"
                >
                  <Trash2 size={14} />
                </button>
                <button
                  onClick={() => { setSelected(null); setEditing(false) }}
                  className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary"
                >
                  <X size={14} />
                </button>
              </div>
            </div>

            {/* Edit form — KMV-QA-014 */}
            {editing ? (
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-content-secondary">Content</label>
                  <textarea
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    rows={6}
                    className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-content-secondary">Content Type</label>
                  <select
                    value={editContentType}
                    onChange={(e) => setEditContentType(e.target.value)}
                    className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm focus:border-brand-primary focus:outline-none"
                  >
                    {['text', 'structured', 'conversation', 'fact', 'preference'].map((ct) => (
                      <option key={ct} value={ct}>{ct}</option>
                    ))}
                  </select>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleSaveEdit}
                    disabled={updateMutation.isPending || !editContent.trim()}
                    className="flex items-center gap-1.5 rounded-lg bg-brand-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-primary/90 disabled:opacity-50"
                  >
                    <Check size={12} />
                    {updateMutation.isPending ? 'Saving…' : 'Save'}
                  </button>
                  <button
                    onClick={() => { setEditing(false); setEditContent(selected.content); setEditContentType(selected.content_type) }}
                    className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
                  >
                    Cancel
                  </button>
                </div>
                {updateMutation.isError && (
                  <p className="text-xs text-status-danger">Failed to save. Please try again.</p>
                )}
              </div>
            ) : (
              /* Read-only detail view */
              <div className="space-y-3 text-sm">
                <div>
                  <div className="mb-1 text-xs font-medium text-content-tertiary">Content</div>
                  <p className="whitespace-pre-wrap text-content-primary">{selected.content}</p>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <div className="text-content-tertiary">Namespace</div>
                    <div className="font-medium">{selected.namespace}</div>
                  </div>
                  <div>
                    <div className="text-content-tertiary">Type</div>
                    <div className="font-medium">{selected.content_type}</div>
                  </div>
                  <div>
                    <div className="text-content-tertiary">Version</div>
                    <div className="font-medium">{selected.version}</div>
                  </div>
                  <div>
                    <div className="text-content-tertiary">Quality</div>
                    <div className="font-medium">
                      {selected.quality_score != null
                        ? `${(selected.quality_score * 100).toFixed(0)}%`
                        : '—'}
                    </div>
                  </div>
                  <div>
                    <div className="text-content-tertiary">Enrichment</div>
                    <StatusBadge status={selected.enrichment_status} />
                  </div>
                  <div>
                    <div className="text-content-tertiary">Source</div>
                    <div className="font-medium">{selected.source_type}</div>
                  </div>
                  <div>
                    <div className="text-content-tertiary">Tier</div>
                    <MemoryLevelBadge tier={(selected as MemoryResponse & { compression_tier?: string }).compression_tier ?? 'L1'} />
                  </div>
                </div>
                <div className="text-xs text-content-tertiary">
                  ID: <code className="rounded bg-surface-tertiary px-1">{selected.memory_id}</code>
                </div>
                <div className="text-xs text-content-tertiary">
                  Created {formatRelativeTime(selected.created_at)}
                </div>
                {/* KMV-S15.3: Expanded memory health (status, weight, decay countdown) */}
                <MemoryHealthBadge
                  weight={(selected as MemoryResponse & { weight?: number | null }).weight ?? null}
                  consolidationStatus={(selected as MemoryResponse & { consolidation_status?: string | null }).consolidation_status ?? null}
                  createdAt={selected.created_at}
                  compact={false}
                />
                {/* F12: Per-memory L2/L3.1 level viewer (namespace-wide L2/L3 + provenance to this memory) */}
                <MemoryLevelsSection
                  namespace={selected.namespace}
                  memoryId={selected.memory_id}
                />
                {/* F12 v2: Per-session L3 rollup (renders only when memory has session_id) */}
                <SessionSummarySection
                  namespace={selected.namespace}
                  sessionId={selected.session_id ?? null}
                />
                {enrichment.data && (
                  <div className="mt-2 rounded-lg bg-surface-secondary p-3">
                    <div className="mb-1 text-xs font-medium text-content-secondary">Enrichment</div>
                    <JsonViewer data={enrichment.data} />
                  </div>
                )}
                {selected.metadata && Object.keys(selected.metadata).length > 0 && (
                  <div>
                    <div className="mb-1 text-xs font-medium text-content-tertiary">Metadata</div>
                    <JsonViewer data={selected.metadata} />
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Delete confirmation dialog — KMV-QA-013 */}
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Delete Memory"
        description={`Are you sure you want to delete this memory? This action cannot be undone.\n\n"${selected?.content?.slice(0, 80)}${(selected?.content?.length ?? 0) > 80 ? '…' : '"'}`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={handleDelete}
      />
    </PageShell>
  )
}
