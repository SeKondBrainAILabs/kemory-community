/**
 * Kemory dashboard — Chats list (chats-v1 UI).
 *
 * List of captured chats with filter chips (namespace, platform, since)
 * and a click-row-to-open side panel. The selected chat id is mirrored
 * into ?chat=… so the panel state survives reloads + can be deep-linked
 * (the standalone /chats/:chatId page covers permalink sharing).
 */
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ExternalLink, Inbox, RefreshCw, Trash2, X } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { PageShell } from '@/components/layout/PageShell'
import { DataTable } from '@/components/shared/DataTable'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { useChatList, useDeleteChat } from '@/hooks/useChats'
import { useNamespaces } from '@/hooks/useMemories'
import { isInboxNamespace } from '@/api/chats'
import type { ChatListItem, Platform } from '@/api/chats'
import { ChatDetailPanel } from './ChatDetailPanel'

const PLATFORMS: Array<{ value: '' | Platform; label: string }> = [
  { value: '', label: 'All platforms' },
  { value: 'chatgpt', label: 'ChatGPT' },
  { value: 'claude', label: 'Claude' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'manus', label: 'Manus' },
  { value: 'other', label: 'Other' },
]

const PAGE_SIZE = 25

function formatRelative(iso: string): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diffSec = Math.round((now - then) / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.round(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffH = Math.round(diffMin / 60)
  if (diffH < 24) return `${diffH}h ago`
  const diffD = Math.round(diffH / 24)
  if (diffD < 30) return `${diffD}d ago`
  return new Date(iso).toLocaleDateString()
}

export function ChatsListPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [namespace, setNamespace] = useState<string>('')
  const [platform, setPlatform] = useState<'' | Platform>('')
  // chats-v1 inbox: client-side "show only inbox" filter. We could push
  // this into the API with a `?inbox=true` flag, but namespace pattern
  // matching on the server requires a new column; for now we fetch as
  // usual and filter the rendered rows. Fine at single-user scale.
  const [inboxOnly, setInboxOnly] = useState(false)
  const [page, setPage] = useState(0)
  const [confirmDelete, setConfirmDelete] = useState<ChatListItem | null>(null)

  const selectedChatId = searchParams.get('chat')

  const namespaces = useNamespaces()
  const qc = useQueryClient()
  const list = useChatList({
    namespace: namespace || undefined,
    platform: (platform || undefined) as Platform | undefined,
    // Pull a larger page when filtering inbox-only so the client-side
    // filter still has enough rows to show.
    limit: inboxOnly ? 100 : PAGE_SIZE,
    offset: page * PAGE_SIZE,
  })
  const deleteMutation = useDeleteChat()

  const totalCount = list.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))

  function selectChat(chatId: string | null) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (chatId) next.set('chat', chatId)
      else next.delete('chat')
      return next
    })
  }

  function handleDelete() {
    if (!confirmDelete) return
    deleteMutation.mutate(confirmDelete.chat_id, {
      onSuccess: () => {
        if (selectedChatId === confirmDelete.chat_id) selectChat(null)
        setConfirmDelete(null)
      },
    })
  }

  const columns = useMemo<ColumnDef<ChatListItem>[]>(
    () => [
      {
        accessorKey: 'platform',
        header: 'Platform',
        cell: ({ row }) => <StatusBadge status={row.original.platform} />,
      },
      {
        accessorKey: 'title',
        header: 'Title',
        cell: ({ row }) => (
          <span className="font-medium text-content-primary">
            {row.original.title || (
              <span className="italic text-content-tertiary">untitled</span>
            )}
          </span>
        ),
      },
      {
        accessorKey: 'namespace',
        header: 'Namespace',
        cell: ({ row }) =>
          isInboxNamespace(row.original.namespace) ? (
            <span
              className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 font-mono text-[11px] font-semibold text-amber-700 ring-1 ring-amber-200"
              title="Sitting in the inbox — open the chat to classify or move it"
            >
              <Inbox size={10} /> {row.original.namespace}
            </span>
          ) : (
            <span className="font-mono text-xs text-content-secondary">
              {row.original.namespace}
            </span>
          ),
      },
      {
        accessorKey: 'turn_count',
        header: 'Turns',
        cell: ({ row }) => <span className="tabular-nums">{row.original.turn_count}</span>,
      },
      {
        accessorKey: 'updated_at',
        header: 'Updated',
        cell: ({ row }) => (
          <span className="text-xs text-content-tertiary" title={row.original.updated_at}>
            {formatRelative(row.original.updated_at)}
          </span>
        ),
      },
      {
        id: 'actions',
        header: '',
        cell: ({ row }) => (
          <div className="flex items-center justify-end gap-1">
            <Link
              to={`/chats/${row.original.chat_id}`}
              onClick={(e) => e.stopPropagation()}
              className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
              title="Open as standalone page"
            >
              <ExternalLink size={14} />
            </Link>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setConfirmDelete(row.original)
              }}
              className="rounded p-1 text-content-tertiary hover:bg-red-50 hover:text-status-danger"
              title="Delete chat"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ),
      },
    ],
    [],
  )

  return (
    <PageShell>
      <div className="mb-4 flex items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-content-primary">Chats</h1>
          <p className="mt-1 text-sm text-content-secondary">
            Raw conversations pushed from the Kanvas Chrome Extension.
          </p>
        </div>
        <button
          type="button"
          onClick={() => qc.invalidateQueries({ queryKey: ['chats', 'list'] })}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-white px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          value={namespace}
          onChange={(e) => {
            setNamespace(e.target.value)
            setPage(0)
          }}
          className="rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none"
        >
          <option value="">All namespaces</option>
          {(namespaces.data ?? []).map((ns) => (
            <option key={ns.namespace} value={ns.namespace}>
              {ns.namespace}
            </option>
          ))}
        </select>
        <select
          value={platform}
          onChange={(e) => {
            setPlatform(e.target.value as '' | Platform)
            setPage(0)
          }}
          className="rounded-lg border border-border bg-white px-3 py-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none"
        >
          {PLATFORMS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => {
            setInboxOnly((v) => !v)
            setPage(0)
          }}
          className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
            inboxOnly
              ? 'border-amber-300 bg-amber-50 text-amber-700'
              : 'border-border bg-white text-content-secondary hover:bg-surface-secondary'
          }`}
          title="Show only chats sitting in kora:inbox:* — typically the ones the extension just pushed"
        >
          <Inbox size={14} />
          {inboxOnly ? 'Inbox only' : 'Inbox'}
        </button>
        <div className="text-xs text-content-tertiary">
          {totalCount} chat{totalCount === 1 ? '' : 's'}
        </div>
      </div>

      <div className="flex gap-4">
        <div className="flex-1 space-y-3">
          {list.isLoading ? (
            <div className="rounded-lg border border-border bg-white p-8 text-center text-sm text-content-tertiary">
              Loading chats…
            </div>
          ) : list.isError ? (
            <div className="rounded-lg border border-status-danger bg-red-50 p-8 text-center text-sm text-status-danger">
              Failed to load chats. {(list.error as Error)?.message}
            </div>
          ) : (list.data?.items.length ?? 0) === 0 ? (
            <div className="rounded-lg border border-border bg-white p-8 text-center text-sm text-content-tertiary">
              No chats yet. Push one from the Chrome Extension or via{' '}
              <code className="rounded bg-surface-secondary px-1 py-0.5 text-[11px]">
                POST /api/v1/chats
              </code>
              .
            </div>
          ) : (
            <>
              <DataTable
                columns={columns}
                data={(list.data?.items ?? []).filter(
                  (r) => !inboxOnly || isInboxNamespace(r.namespace),
                )}
                onRowClick={(row) => selectChat(row.chat_id)}
              />
              <div className="flex items-center justify-between text-xs text-content-tertiary">
                <span>
                  Page {page + 1} of {totalPages}
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={page === 0}
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    className="rounded border border-border px-2 py-1 disabled:opacity-40"
                  >
                    Prev
                  </button>
                  <button
                    type="button"
                    disabled={page + 1 >= totalPages}
                    onClick={() => setPage((p) => p + 1)}
                    className="rounded border border-border px-2 py-1 disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </div>

        {selectedChatId && (
          <aside className="w-[480px] shrink-0 overflow-hidden rounded-lg border border-border bg-white">
            <div className="flex items-center justify-between border-b border-border bg-surface-secondary/40 px-3 py-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-content-secondary">
                Chat detail
              </span>
              <div className="flex items-center gap-1">
                <Link
                  to={`/chats/${selectedChatId}`}
                  className="rounded p-1 text-content-tertiary hover:bg-white hover:text-content-primary"
                  title="Open as full page"
                >
                  <ExternalLink size={14} />
                </Link>
                <button
                  type="button"
                  onClick={() => selectChat(null)}
                  className="rounded p-1 text-content-tertiary hover:bg-white hover:text-content-primary"
                >
                  <X size={14} />
                </button>
              </div>
            </div>
            <div className="h-[calc(100vh-220px)] overflow-y-auto">
              <ChatDetailPanel chatId={selectedChatId} />
            </div>
          </aside>
        )}
      </div>

      <ConfirmDialog
        open={!!confirmDelete}
        onOpenChange={(open) => !open && setConfirmDelete(null)}
        title="Delete chat?"
        description={
          confirmDelete
            ? `This will soft-delete "${confirmDelete.title || confirmDelete.platform_conversation_id}" and all its turns + artifacts. The chat will no longer be visible in the dashboard.`
            : ''
        }
        confirmLabel="Delete"
        variant="danger"
        onConfirm={handleDelete}
      />
    </PageShell>
  )
}
