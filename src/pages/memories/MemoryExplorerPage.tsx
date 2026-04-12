/**
 * Memory Vault — Memory Explorer Page
 *
 * EPIC-002 fixes:
 *   KMV-QA-013: Add Delete Memory button with confirmation dialog
 *   KMV-QA-014: Add Edit Memory inline form in the detail panel
 *   KMV-QA-015: Add pagination controls (offset-based, 50 per page)
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
import { X, Trash2, Pencil, ChevronLeft, ChevronRight, Check } from 'lucide-react'

const PAGE_SIZE = 50

const contentTypes = ['all', 'text', 'structured', 'conversation', 'fact', 'preference'] as const

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

export function MemoryExplorerPage() {
  const [query, setQuery] = useState('')
  const [namespace, setNamespace] = useState<string>('')
  const [contentType, setContentType] = useState('all')
  const [selected, setSelected] = useState<MemoryResponse | null>(null)
  const [page, setPage] = useState(0)

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
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
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
      </div>

      <div className="flex gap-4">
        {/* Table */}
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
                </div>
                <div className="text-xs text-content-tertiary">
                  ID: <code className="rounded bg-surface-tertiary px-1">{selected.memory_id}</code>
                </div>
                <div className="text-xs text-content-tertiary">
                  Created {formatRelativeTime(selected.created_at)}
                </div>
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

