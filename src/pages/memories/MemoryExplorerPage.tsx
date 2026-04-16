/**
 * Memory Vault — Memory Explorer Page (KMV-E15 UX Redesign)
 *
 * KMV-S15.1: Non-Technical Default View & Advanced Toggle
 *   - Global Advanced toggle (persisted in localStorage)
 *   - Default view: plain-English labels, content previews, relative timestamps
 *   - Advanced view: UUIDs, raw JSON, technical metadata
 *
 * KMV-S15.2: Namespace Summary Header
 *   - Compact collapsible header above the memory list
 *   - Shows status counts, avg weight bar, health sentence
 *   - Expandable policy editor + manual sync trigger
 *
 * KMV-S15.3: Inline Memory Health & Decay Indicators
 *   - Per-row: status badge, weight bar/number, days until archived, days until floor
 *   - Light non-error palette (indigo/blue/slate/emerald)
 *   - User-selectable weight display mode (bar vs number)
 *
 * Previous fixes retained:
 *   KMV-QA-013: Delete Memory with confirmation dialog
 *   KMV-QA-014: Edit Memory inline form
 *   KMV-QA-015: Pagination controls (offset-based, 50 per page)
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
} from '@/hooks/useMemories'
import { formatRelativeTime } from '@/lib/utils'
import { cn } from '@/lib/utils'
import type { MemoryResponse } from '@/api/types'
import { X, Trash2, Pencil, ChevronLeft, ChevronRight, Check, BarChart2, Hash, SlidersHorizontal } from 'lucide-react'
import { MemoryHealthBadge } from '@/components/memories/MemoryHealthBadge'
import { NamespaceSummaryHeader } from '@/components/memories/NamespaceSummaryHeader'
import { AdvancedViewProvider, useAdvancedView } from '@/contexts/AdvancedViewContext'

const PAGE_SIZE = 50
const contentTypes = ['all', 'text', 'structured', 'conversation', 'fact', 'preference'] as const

// ─── Advanced toggle button ────────────────────────────────────────────────────

function AdvancedToggle() {
  const { advanced, toggle } = useAdvancedView()
  return (
    <button
      onClick={toggle}
      title={advanced ? 'Switch to simple view' : 'Switch to advanced developer view'}
      className={cn(
        'flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
        advanced
          ? 'border-indigo-200 bg-indigo-50 text-indigo-700'
          : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50',
      )}
    >
      <SlidersHorizontal size={12} />
      {advanced ? 'Advanced' : 'Simple'}
    </button>
  )
}

// ─── Weight display toggle ─────────────────────────────────────────────────────

function WeightDisplayToggle({
  mode,
  onChange,
}: {
  mode: 'bar' | 'number'
  onChange: (m: 'bar' | 'number') => void
}) {
  return (
    <div className="flex items-center rounded-lg border border-slate-200 bg-white">
      <button
        onClick={() => onChange('bar')}
        title="Show weight as bar"
        className={cn(
          'flex items-center gap-1 rounded-l-lg px-2.5 py-1.5 text-xs transition-colors',
          mode === 'bar'
            ? 'bg-indigo-50 text-indigo-700'
            : 'text-slate-400 hover:bg-slate-50',
        )}
      >
        <BarChart2 size={11} />
      </button>
      <button
        onClick={() => onChange('number')}
        title="Show weight as number"
        className={cn(
          'flex items-center gap-1 rounded-r-lg px-2.5 py-1.5 text-xs transition-colors',
          mode === 'number'
            ? 'bg-indigo-50 text-indigo-700'
            : 'text-slate-400 hover:bg-slate-50',
        )}
      >
        <Hash size={11} />
      </button>
    </div>
  )
}

// ─── Column definitions ────────────────────────────────────────────────────────

function buildColumns(
  advanced: boolean,
  weightDisplay: 'bar' | 'number',
): ColumnDef<MemoryResponse, unknown>[] {
  const base: ColumnDef<MemoryResponse, unknown>[] = [
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
      id: 'health',
      header: 'Health',
      cell: ({ row }) => (
        <MemoryHealthBadge
          weight={(row.original as MemoryResponse & { consolidation_weight?: number }).consolidation_weight}
          consolidationStatus={(row.original as MemoryResponse & { consolidation_status?: string }).consolidation_status}
          createdAt={row.original.created_at}
          weightDisplay={weightDisplay}
          compact
        />
      ),
    },
    {
      accessorKey: 'created_at',
      header: 'Created',
      cell: ({ getValue }) => (
        <span className="text-xs text-slate-400">{formatRelativeTime(getValue() as string)}</span>
      ),
    },
  ]

  if (advanced) {
    base.splice(3, 0, {
      accessorKey: 'enrichment_status',
      header: 'Enrichment',
      cell: ({ getValue }) => <StatusBadge status={getValue() as string} />,
    })
    base.push({
      accessorKey: 'version',
      header: 'Ver',
    })
  }

  return base
}

// ─── Detail panel ──────────────────────────────────────────────────────────────

function DetailPanel({
  selected,
  editing,
  editContent,
  editContentType,
  weightDisplay,
  onEdit,
  onCancelEdit,
  onSaveEdit,
  onDelete,
  onClose,
  onEditContentChange,
  onEditContentTypeChange,
  updatePending,
  updateError,
  enrichmentData,
}: {
  selected: MemoryResponse & { consolidation_weight?: number; consolidation_status?: string }
  editing: boolean
  editContent: string
  editContentType: string
  weightDisplay: 'bar' | 'number'
  onEdit: () => void
  onCancelEdit: () => void
  onSaveEdit: () => void
  onDelete: () => void
  onClose: () => void
  onEditContentChange: (v: string) => void
  onEditContentTypeChange: (v: string) => void
  updatePending: boolean
  updateError: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  enrichmentData: any
}) {
  const { advanced } = useAdvancedView()

  return (
    <div className="w-96 shrink-0 rounded-lg border border-border bg-white p-4">
      {/* Panel header */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-content-primary">Memory Detail</h3>
        <div className="flex items-center gap-1">
          {!editing && (
            <button
              onClick={onEdit}
              className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-brand-primary"
              title="Edit memory"
            >
              <Pencil size={14} />
            </button>
          )}
          <button
            onClick={onDelete}
            className="rounded p-1.5 text-content-tertiary hover:bg-red-50 hover:text-status-danger"
            title="Delete memory"
          >
            <Trash2 size={14} />
          </button>
          <button
            onClick={onClose}
            className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {editing ? (
        /* ── Edit form ── */
        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-content-secondary">Content</label>
            <textarea
              value={editContent}
              onChange={(e) => onEditContentChange(e.target.value)}
              rows={6}
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-content-secondary">Content Type</label>
            <select
              value={editContentType}
              onChange={(e) => onEditContentTypeChange(e.target.value)}
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm focus:border-brand-primary focus:outline-none"
            >
              {['text', 'structured', 'conversation', 'fact', 'preference'].map((ct) => (
                <option key={ct} value={ct}>{ct}</option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <button
              onClick={onSaveEdit}
              disabled={updatePending || !editContent.trim()}
              className="flex items-center gap-1.5 rounded-lg bg-brand-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-primary/90 disabled:opacity-50"
            >
              <Check size={12} />
              {updatePending ? 'Saving…' : 'Save'}
            </button>
            <button
              onClick={onCancelEdit}
              className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
            >
              Cancel
            </button>
          </div>
          {updateError && (
            <p className="text-xs text-status-danger">Failed to save. Please try again.</p>
          )}
        </div>
      ) : (
        /* ── Read-only view ── */
        <div className="space-y-3 text-sm">
          {/* Content */}
          <div>
            <div className="mb-1 text-xs font-medium text-content-tertiary">Content</div>
            <p className="whitespace-pre-wrap text-content-primary">{selected.content}</p>
          </div>

          {/* Memory health — expanded mode */}
          <MemoryHealthBadge
            weight={selected.consolidation_weight}
            consolidationStatus={selected.consolidation_status}
            createdAt={selected.created_at}
            weightDisplay={weightDisplay}
            compact={false}
          />

          {/* Core metadata grid */}
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
              <div className="text-content-tertiary">Source</div>
              <div className="font-medium">{selected.source_type}</div>
            </div>
            <div>
              <div className="text-content-tertiary">Quality</div>
              <div className="font-medium">
                {selected.quality_score != null
                  ? `${(selected.quality_score * 100).toFixed(0)}%`
                  : '—'}
              </div>
            </div>
            {advanced && (
              <>
                <div>
                  <div className="text-content-tertiary">Version</div>
                  <div className="font-medium">{selected.version}</div>
                </div>
                <div>
                  <div className="text-content-tertiary">Enrichment</div>
                  <StatusBadge status={selected.enrichment_status} />
                </div>
              </>
            )}
          </div>

          {/* Technical IDs — advanced only */}
          {advanced && (
            <>
              <div className="text-xs text-content-tertiary">
                ID: <code className="rounded bg-surface-tertiary px-1">{selected.memory_id}</code>
              </div>
              {(selected as MemoryResponse & { cognition_entity_id?: string }).cognition_entity_id && (
                <div className="text-xs text-content-tertiary">
                  Cognition ID:{' '}
                  <code className="rounded bg-surface-tertiary px-1">
                    {(selected as MemoryResponse & { cognition_entity_id?: string }).cognition_entity_id}
                  </code>
                </div>
              )}
            </>
          )}

          <div className="text-xs text-content-tertiary">
            Created {formatRelativeTime(selected.created_at)}
          </div>

          {/* Enrichment data */}
          {enrichmentData && (
            <div className="mt-2 rounded-lg bg-surface-secondary p-3">
              <div className="mb-1 text-xs font-medium text-content-secondary">Enrichment</div>
              <JsonViewer data={enrichmentData} />
            </div>
          )}

          {/* Raw metadata — advanced only */}
          {advanced && selected.metadata && Object.keys(selected.metadata).length > 0 && (
            <div>
              <div className="mb-1 text-xs font-medium text-content-tertiary">Metadata</div>
              <JsonViewer data={selected.metadata} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Main page ─────────────────────────────────────────────────────────────────

function MemoryExplorerPageInner() {
  const { advanced } = useAdvancedView()
  const [query, setQuery] = useState('')
  const [namespace, setNamespace] = useState<string>('')
  const [contentType, setContentType] = useState('all')
  const [selected, setSelected] = useState<MemoryResponse | null>(null)
  const [page, setPage] = useState(0)
  const [weightDisplay, setWeightDisplay] = useState<'bar' | 'number'>('bar')

  // Edit state
  const [editing, setEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [editContentType, setEditContentType] = useState('')

  // Namespace search filter
  const [nsFilter, setNsFilter] = useState('')

  // Delete confirm
  const [confirmDelete, setConfirmDelete] = useState(false)

  const namespaces = useNamespaces()
  const search = useMemorySearch({
    query: query || undefined,
    namespace: namespace || undefined,
    content_type: contentType === 'all' ? undefined : contentType,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  })

  const enrichment = useMemoryEnrichment(selected?.memory_id ?? '')
  const deleteMutation = useDeleteMemory()
  const updateMutation = useUpdateMemory()

  const totalCount = search.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))
  const columns = buildColumns(advanced, weightDisplay)

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
        data: { content: editContent, content_type: editContentType || undefined },
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
      {/* ── Toolbar ── */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SearchInput
          value={query}
          onChange={(v) => { setQuery(v); setPage(0) }}
          placeholder="Search memories…"
          className="w-64"
        />

        {/* Namespace selector */}
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
                nsFilter === '' || ns.namespace.toLowerCase().includes(nsFilter.toLowerCase())
              )
              .map((ns) => (
                <option key={ns.namespace} value={ns.namespace}>
                  {ns.namespace} ({ns.count})
                </option>
              ))}
          </select>
        </div>

        {/* Content type pills */}
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

        {/* Weight display toggle */}
        <WeightDisplayToggle mode={weightDisplay} onChange={setWeightDisplay} />

        {/* Advanced toggle — pushed to the right */}
        <div className="ml-auto">
          <AdvancedToggle />
        </div>
      </div>

      {/* ── Namespace Summary Header (KMV-S15.2) ── */}
      {namespace && (
        <div className="mb-3">
          <NamespaceSummaryHeader
            namespace={namespace}
            totalMemories={totalCount}
          />
        </div>
      )}

      <div className="flex gap-4">
        {/* ── Memory list ── */}
        <div className="min-w-0 flex-1">
          {search.isLoading ? (
            <LoadingSkeleton lines={10} />
          ) : (
            <>
              <DataTable
                columns={columns}
                data={search.data?.items ?? []}
                onRowClick={openDetail}
              />
              {/* Pagination */}
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

        {/* ── Detail panel ── */}
        {selected && (
          <DetailPanel
            selected={selected as MemoryResponse & { consolidation_weight?: number; consolidation_status?: string }}
            editing={editing}
            editContent={editContent}
            editContentType={editContentType}
            weightDisplay={weightDisplay}
            onEdit={() => setEditing(true)}
            onCancelEdit={() => { setEditing(false); setEditContent(selected.content); setEditContentType(selected.content_type) }}
            onSaveEdit={handleSaveEdit}
            onDelete={() => setConfirmDelete(true)}
            onClose={() => { setSelected(null); setEditing(false) }}
            onEditContentChange={setEditContent}
            onEditContentTypeChange={setEditContentType}
            updatePending={updateMutation.isPending}
            updateError={updateMutation.isError}
            enrichmentData={enrichment.data}
          />
        )}
      </div>

      {/* ── Delete confirmation ── */}
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

// Wrap with the AdvancedViewProvider so the toggle is available everywhere
export function MemoryExplorerPage() {
  return (
    <AdvancedViewProvider>
      <MemoryExplorerPageInner />
    </AdvancedViewProvider>
  )
}
