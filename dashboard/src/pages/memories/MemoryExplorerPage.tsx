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
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { type ColumnDef } from '@tanstack/react-table'
import { PageShell } from '@/components/layout/PageShell'
import { DataTable } from '@/components/shared/DataTable'
import { Pagination } from '@/components/shared/Pagination'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { SearchInput } from '@/components/shared/SearchInput'
import { EmptyState } from '@/components/shared/EmptyState'
import { JsonViewer } from '@/components/shared/JsonViewer'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import {
  useMemorySearch,
  useNamespaces,
  useMemoryEnrichment,
  useMemoryHistory,
  useDeleteMemory,
  useUpdateMemory,
  useMemoryLevel,
} from '@/hooks/useMemories'
import { formatRelativeTime, formatAbsoluteTime } from '@/lib/utils'
import { cn } from '@/lib/utils'
import type { MemoryResponse, MemoryEvent } from '@/api/types'
import type { MemoryReadMode } from '@/api/memories'
import {
  X,
  Trash2,
  Pencil,
  Check,
  Layers,
  Copy,
  ClipboardCheck,
  History as HistoryIcon,
  FileText,
  ArrowLeftRight,
} from 'lucide-react'
import { MarkdownView } from '@/components/shared/MarkdownView'
import { MemoryCard } from '@/components/memories/MemoryCard'
import { NamespaceCombobox } from '@/components/memories/NamespaceCombobox'
import { useUrlState } from '@/hooks/useUrlState'
import { NamespaceSummaryHeader } from '@/components/memories/NamespaceSummaryHeader'
import { MemoryHealthBadge } from '@/components/memories/MemoryHealthBadge'
import { MemoryLevelsSection } from '@/components/memories/MemoryLevelsSection'
import { SessionSummarySection } from '@/components/memories/SessionSummarySection'
import { MemoryLevelBadge, MemoryLevelLegend } from '@/components/shared/MemoryLevelBadge'

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

// S9N-6163: wrap query terms in the content column with <mark>. Each
// whitespace-separated term is highlighted case-insensitively; the query is
// regex-escaped so punctuation in a search can't break the pattern.
function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function highlightMatch(text: string, query: string): ReactNode {
  const terms = query.trim().split(/\s+/).filter(Boolean).map(escapeRegExp)
  if (!terms.length) return text
  // Single capturing group → String.split alternates [text, match, text, …],
  // so the matched fragments land on the odd indices.
  const parts = text.split(new RegExp(`(${terms.join('|')})`, 'ig'))
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} className="rounded bg-amber-200 px-0.5 text-content-primary">
        {part}
      </mark>
    ) : (
      part
    ),
  )
}

// S9N-6163: columns are built per-render so the content cell can highlight the
// active query. Kept as a pure builder + useMemo (not a module const) to avoid
// rebuilding the array on every keystroke while still tracking the query.
function buildColumns(
  query: string,
  timeField: 'created' | 'updated',
  onToggleTimeField: () => void,
): ColumnDef<MemoryResponse, unknown>[] {
  return [
  {
    accessorKey: 'content',
    header: 'Content',
    cell: ({ row, getValue }) => {
      // S9N-6163: relevance chip when the row carries a search score
      const rel = row.original.similarity_score
      return (
        <div className="flex max-w-sm items-start gap-2">
          <span className="line-clamp-2 text-sm">
            {highlightMatch(getValue() as string, query)}
          </span>
          {rel != null && (
            <span
              className="mt-0.5 shrink-0 rounded bg-brand-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-brand-primaryDark"
              title="Search relevance"
            >
              {Math.round(rel * 100)}%
            </span>
          )}
        </div>
      )
    },
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
    // S9N-6166: Age column — relative time + absolute tooltip, sortable,
    // with a header toggle between created_at and updated_at. Dates read
    // newest-first, so the first sort click should be descending.
    id: 'age',
    sortDescFirst: true,
    accessorFn: (row) => (timeField === 'created' ? row.created_at : row.updated_at),
    header: () => (
      <span className="inline-flex items-center gap-1">
        {timeField === 'created' ? 'Created' : 'Updated'}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onToggleTimeField()
          }}
          title={`Show ${timeField === 'created' ? 'updated' : 'created'} time`}
          aria-label={`Show ${timeField === 'created' ? 'updated' : 'created'} time`}
          className="rounded p-0.5 text-content-tertiary hover:bg-surface-tertiary hover:text-content-primary"
        >
          <ArrowLeftRight size={11} />
        </button>
      </span>
    ),
    cell: ({ getValue }) => {
      const v = getValue() as string
      return <span title={formatAbsoluteTime(v)}>{formatRelativeTime(v)}</span>
    },
  },
  ]
}

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
  const url = useUrlState()
  const pageSize = [25, 50, 100].includes(Number(url.get('size'))) ? Number(url.get('size')) : 50
  const page = Math.max(0, (parseInt(url.get('page', '1'), 10) || 1) - 1)
  const setPage = useCallback(
    (nextPage: number) => url.set({ page: nextPage === 0 ? null : String(nextPage + 1) }),
    [url],
  )
  const setPageSize = useCallback(
    (size: number) => url.set({ size: size === 50 ? null : String(size), page: null }),
    [url],
  )

  // KMV-S12.1: Memory level toggle state
  const [memoryLevel, setMemoryLevel] = useState<MemoryReadMode>('raw')
  const [showLevelView, setShowLevelView] = useState(false)

  // Edit state
  const [editing, setEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [editContentType, setEditContentType] = useState('')

  // Delete confirm dialog
  const [confirmDelete, setConfirmDelete] = useState(false)

  // S9N-6166: which timestamp the Age column shows/sorts by
  const [timeField, setTimeField] = useState<'created' | 'updated'>('created')

  // S9N-6164: detail panel v2 — tab, copy feedback, focus restore refs
  const [panelTab, setPanelTab] = useState<'details' | 'history'>('details')
  const [copied, setCopied] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const lastFocusedRef = useRef<HTMLElement | null>(null)

  const namespaces = useNamespaces()
  const search = useMemorySearch({
    query: query || undefined,
    namespace: namespace || undefined,
    content_type: contentType === 'all' ? undefined : contentType,
    compression_tier: tier === 'all' ? undefined : tier,
    limit: pageSize,
    offset: page * pageSize,
    // Hybrid mode tolerates an empty query (falls back to a plain SQL
    // listing) whereas fts mode returns 422. Keeps the Explorer populated
    // on first open, before the user has typed anything.
    search_mode: 'hybrid',
  })

  const enrichment = useMemoryEnrichment(selected?.memory_id ?? '')
  // S9N-6164: history only fetched while the History tab is open on a selection
  const history = useMemoryHistory(
    selected?.memory_id ?? '',
    !!selected && panelTab === 'history',
  )
  const deleteMutation = useDeleteMemory()
  const updateMutation = useUpdateMemory()

  const totalCount = search.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))

  // S9N-6163/6166: columns depend on the active query (highlighting) and the
  // selected timestamp field (Age column).
  const columns = useMemo(
    () =>
      buildColumns(query, timeField, () =>
        setTimeField((f) => (f === 'created' ? 'updated' : 'created')),
      ),
    [query, timeField],
  )
  // In-flight shimmer: isLoading only covers the first fetch; isFetching stays
  // true on every refetch, so a query change dims the (placeholder) rows while
  // the new results load instead of the table looking frozen.
  const isSearching = search.isFetching && !search.isLoading

  function openDetail(row: MemoryResponse) {
    // S9N-6164: remember the trigger so focus can return to it on close
    lastFocusedRef.current = document.activeElement as HTMLElement | null
    setSelected(row)
    setEditing(false)
    setPanelTab('details')
    setEditContent(row.content)
    setEditContentType(row.content_type)
  }

  // S9N-6164: single close path — clears selection and restores focus to the
  // row (or whatever opened the panel) for a keyboard round-trip.
  function closePanel() {
    setSelected(null)
    setEditing(false)
    setPanelTab('details')
    lastFocusedRef.current?.focus?.()
  }

  // S9N-6164: Escape closes the panel; outside-click closes it too. Editing
  // guards Escape so a mid-edit Escape doesn't discard silently — it exits edit
  // mode first, then a second Escape closes.
  useEffect(() => {
    if (!selected) return
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return
      if (editing) {
        setEditing(false)
        return
      }
      closePanel()
    }
    function onClick(e: MouseEvent) {
      if (editing || confirmDelete) return
      const el = panelRef.current
      const target = e.target as Node | null
      if (el && target && !el.contains(target)) closePanel()
    }
    window.addEventListener('keydown', onKey)
    // capture=false, and defer click binding a tick so the opening click
    // doesn't immediately close the panel.
    const t = window.setTimeout(() => document.addEventListener('mousedown', onClick), 0)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.clearTimeout(t)
      document.removeEventListener('mousedown', onClick)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, editing, confirmDelete])

  async function handleCopyContent() {
    if (!selected) return
    try {
      await navigator.clipboard.writeText(selected.content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard blocked (insecure context / permissions) — no-op
    }
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
          className="w-full sm:w-64"
          hotkey
        />
        <NamespaceCombobox
          namespaces={namespaces.data ?? []}
          value={namespace}
          totalCount={namespaces.data?.reduce((sum, item) => sum + item.count, 0) ?? 0}
          onChange={(value) => {
            setNamespace(value)
            setPage(0)
          }}
        />
        <div className="flex flex-wrap gap-1">
          {contentTypes.map((ct) => (
            <button
              key={ct}
              onClick={() => { setContentType(ct); setPage(0) }}
              className={cn(
                'rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors',
                contentType === ct
                  ? 'bg-brand-primaryDark text-white'
                  : 'border border-border bg-white text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {ct}
            </button>
          ))}
        </div>

        {/* F12: Compression tier filter pills (L1 / L2 / L3.1) */}
        <div className="flex flex-wrap items-center gap-1" title="Filter by memory compression tier">
          {tiers.map((t) => (
            <button
              key={t}
              onClick={() => { setTier(t); setPage(0) }}
              className={cn(
                'rounded-full px-3 py-1 text-xs font-medium transition-colors',
                tier === t
                  ? 'bg-brand-primaryDark text-white'
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
                ? 'border-brand-primaryDark bg-brand-primaryDark text-white'
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
      <div className="mb-3 overflow-x-auto px-1">
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
              aria-label="Close memory levels"
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
          ) : (search.data?.items?.length ?? 0) === 0 ? (
            <EmptyState
              title={query ? `No memories match “${query}”` : 'No memories yet'}
              description={
                query
                  ? 'Try a different search, or clear it to browse everything.'
                  : 'Memories your agents store will appear here.'
              }
              action={
                query ? { label: 'Clear search', onClick: () => { setQuery(''); setPage(0) } } : undefined
              }
            />
          ) : (
            <>
              {/* S9N-6167: table on ≥768px, card list below */}
              <div
                className={cn(
                  'hidden transition-opacity md:block',
                  isSearching && 'pointer-events-none animate-pulse opacity-50',
                )}
                aria-busy={isSearching}
              >
                <DataTable
                  // S9N-6166: browse defaults to newest-first; an active
                  // search keeps the backend relevance order (no client sort).
                  // Remount on mode change so the default re-seeds.
                  key={query ? 'search' : 'browse'}
                  columns={columns}
                  data={search.data?.items ?? []}
                  onRowClick={openDetail}
                  initialSorting={query ? [] : [{ id: 'age', desc: true }]}
                  stickyHeader
                  maxHeight="calc(100vh - 15rem)"
                />
              </div>
              <div
                className={cn(
                  'space-y-2 transition-opacity md:hidden',
                  isSearching && 'pointer-events-none animate-pulse opacity-50',
                )}
                aria-busy={isSearching}
              >
                {(search.data?.items ?? []).map((m) => (
                  <MemoryCard key={m.memory_id} memory={m} timeField={timeField} onClick={openDetail} />
                ))}
              </div>
              <Pagination
                page={page}
                pageCount={totalPages}
                pageSize={pageSize}
                total={totalCount}
                label={query ? 'results' : 'memories'}
                onPageChange={setPage}
                onPageSizeChange={setPageSize}
              />
            </>
          )}
        </div>

        {/* Detail panel */}
        {selected && (
          <div
            ref={panelRef}
            role="dialog"
            aria-label="Memory detail"
            className="fixed inset-0 z-50 w-full overflow-y-auto border-border bg-white p-4 md:static md:z-auto md:w-96 md:shrink-0 md:self-start md:overflow-visible md:rounded-lg md:border"
          >
            {/* Panel header */}
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-content-primary">Memory Detail</h3>
              <div className="flex items-center gap-1">
                <button
                  onClick={handleCopyContent}
                  className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-brand-primary"
                  title={copied ? 'Copied!' : 'Copy content'}
                  aria-label={copied ? 'Content copied' : 'Copy content'}
                >
                  {copied ? <ClipboardCheck size={14} className="text-status-success" /> : <Copy size={14} />}
                </button>
                {!editing && (
                  <button
                    onClick={() => setEditing(true)}
                    className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-brand-primary"
                    title="Edit memory"
                    aria-label="Edit memory"
                  >
                    <Pencil size={14} />
                  </button>
                )}
                <button
                  onClick={() => setConfirmDelete(true)}
                  className="rounded p-1.5 text-content-tertiary hover:bg-red-50 hover:text-status-danger"
                  title="Delete memory"
                  aria-label="Delete memory"
                >
                  <Trash2 size={14} />
                </button>
                <button
                  onClick={closePanel}
                  aria-label="Close detail panel"
                  title="Close (Esc)"
                  className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary"
                >
                  <X size={14} />
                </button>
              </div>
            </div>

            {/* S9N-6164: Details / History tabs (hidden while editing) */}
            {!editing && (
              <div className="mb-3 flex gap-1 border-b border-border" role="tablist" aria-label="Memory detail tabs">
                <button
                  role="tab"
                  aria-selected={panelTab === 'details'}
                  onClick={() => setPanelTab('details')}
                  className={cn(
                    'flex items-center gap-1.5 border-b-2 px-2 py-1.5 text-xs font-medium',
                    panelTab === 'details'
                      ? 'border-brand-primary text-brand-primaryDark'
                      : 'border-transparent text-content-secondary hover:text-content-primary',
                  )}
                >
                  <FileText size={13} /> Details
                </button>
                <button
                  role="tab"
                  aria-selected={panelTab === 'history'}
                  onClick={() => setPanelTab('history')}
                  className={cn(
                    'flex items-center gap-1.5 border-b-2 px-2 py-1.5 text-xs font-medium',
                    panelTab === 'history'
                      ? 'border-brand-primary text-brand-primaryDark'
                      : 'border-transparent text-content-secondary hover:text-content-primary',
                  )}
                >
                  <HistoryIcon size={13} /> History
                </button>
              </div>
            )}

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
            ) : panelTab === 'history' ? (
              /* S9N-6164: provenance timeline from the history endpoint */
              <div className="space-y-2 text-sm">
                {history.isLoading ? (
                  <LoadingSkeleton lines={4} />
                ) : history.isError ? (
                  <p className="text-xs text-status-danger">Failed to load history.</p>
                ) : (history.data?.length ?? 0) === 0 ? (
                  <p className="text-xs italic text-content-tertiary">No provenance events recorded.</p>
                ) : (
                  <ol className="relative space-y-3 border-l border-border pl-4">
                    {history.data!.map((ev: MemoryEvent) => (
                      <li key={ev.event_id} className="relative">
                        <span className="absolute -left-[21px] top-1 h-2 w-2 rounded-full bg-brand-primary" />
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-semibold text-content-primary">{ev.event_type}</span>
                          <span className="text-[10px] text-content-tertiary" title={ev.created_at}>
                            {formatRelativeTime(ev.created_at)}
                          </span>
                        </div>
                        <div className="text-xs text-content-secondary">
                          {ev.actor_type}
                          {ev.actor_id ? ` · ${ev.actor_id}` : ''}
                        </div>
                        {ev.reason && (
                          <div className="mt-0.5 text-xs text-content-tertiary">{ev.reason}</div>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            ) : (
              /* Read-only detail view */
              <div className="space-y-3 text-sm">
                <div>
                  <div className="mb-1 text-xs font-medium text-content-tertiary">Content</div>
                  <MarkdownView content={selected.content} />
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
                  <div className="col-span-2">
                    <div className="text-content-tertiary">Source agent</div>
                    <div className="break-all font-medium">{selected.source_agent_id ?? '—'}</div>
                  </div>
                </div>
                <div className="text-xs text-content-tertiary">
                  ID: <code className="rounded bg-surface-tertiary px-1">{selected.memory_id}</code>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-content-tertiary">
                  <span title={selected.created_at}>Created {formatRelativeTime(selected.created_at)}</span>
                  <span title={selected.updated_at}>Updated {formatRelativeTime(selected.updated_at)}</span>
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
