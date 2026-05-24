/**
 * Shared chat-detail content used by both the side-panel and the
 * standalone full-page deep link (/chats/:chatId).
 *
 * Self-contained — pass it a chatId and it handles the fetch +
 * loading/error states + render. No assumption about a "close"
 * affordance; the wrapper that owns the layout decides whether to
 * show a back button vs an X.
 */
import { useState } from 'react'
import { Inbox, Lightbulb, MoveRight } from 'lucide-react'
import { useChat, useClassifyChat, useMoveChat } from '@/hooks/useChats'
import { isInboxNamespace } from '@/api/chats'
import { ChatTurnView } from '@/components/chats/ChatTurnView'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { cn } from '@/lib/utils'

interface Props {
  chatId: string | null
}

// chats-v1 inbox: suggestion-pill button. Pure presentational; click
// handler is wired by the parent panel because it owns the move
// mutation state (in-flight, manual-input toggle, etc.).
function SuggestionPill({
  namespace,
  similarity,
  signal,
  memoryCount,
  chatCount,
  onMove,
  disabled,
}: {
  namespace: string
  similarity: number
  signal: 'summary' | 'description' | 'name'
  memoryCount: number
  chatCount: number
  onMove: () => void
  disabled?: boolean
}) {
  const pct = Math.round(similarity * 100)
  return (
    <button
      type="button"
      onClick={onMove}
      disabled={disabled}
      className={cn(
        'group flex w-full items-center justify-between gap-3 rounded-md border border-border bg-white px-3 py-2 text-left transition-colors',
        'hover:border-brand-primary hover:bg-brand-primary/[0.04]',
        disabled && 'opacity-50',
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-[12px] font-semibold text-content-primary">
          {namespace}
        </div>
        <div className="mt-0.5 text-[10px] text-content-tertiary">
          {memoryCount} memories · {chatCount} chats · signal: {signal}
        </div>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-content-secondary">
        <span className="rounded-full bg-surface-secondary px-2 py-0.5 font-mono tabular-nums">
          {pct}%
        </span>
        <MoveRight
          size={14}
          className="text-content-tertiary transition-colors group-hover:text-brand-primary"
        />
      </div>
    </button>
  )
}

export function ChatDetailPanel({ chatId }: Props) {
  const { data: chat, isLoading, isError, error } = useChat(chatId)
  const inbox = isInboxNamespace(chat?.namespace ?? null)
  // Classify-on-demand for inbox chats so the panel surfaces destination
  // suggestions immediately; for non-inbox chats the user can still hit
  // "Show suggestions" to override / re-classify.
  const [classifyOpen, setClassifyOpen] = useState(false)
  const showSuggestions = inbox || classifyOpen
  const classify = useClassifyChat(chatId, showSuggestions)
  const moveMutation = useMoveChat()
  const [manualTarget, setManualTarget] = useState('')

  if (!chatId) {
    return (
      <div className="p-6 text-center text-sm text-content-tertiary">
        Select a chat to see its turns and artifacts.
      </div>
    )
  }

  if (isLoading) {
    return <div className="p-6 text-sm text-content-tertiary">Loading chat…</div>
  }

  if (isError || !chat) {
    return (
      <div className="p-6 text-sm text-status-danger">
        Failed to load chat. {(error as Error | undefined)?.message ?? ''}
      </div>
    )
  }

  const turns = chat.turns ?? []

  function doMove(namespace: string) {
    if (!chatId) return
    moveMutation.mutate(
      { chatId, data: { namespace } },
      {
        onSuccess: () => {
          setClassifyOpen(false)
          setManualTarget('')
        },
      },
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border bg-surface-secondary/40 p-4">
        <div className="mb-2 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-content-primary">
              {chat.title || `${chat.platform} conversation`}
            </h3>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-content-tertiary">
              <StatusBadge status={chat.platform} />
              <span>
                namespace ·{' '}
                <span className={cn('font-mono', inbox && 'font-semibold text-amber-700')}>
                  {chat.namespace}
                </span>
              </span>
              {chat.requested_namespace && chat.requested_namespace !== chat.namespace && (
                <span title="The matcher auto-redirected from this">
                  ↳ from {chat.requested_namespace}
                </span>
              )}
              {chat.model && <span>model · {chat.model}</span>}
              <span>{chat.turn_count} turns</span>
            </div>
            {(chat.source_project_name || chat.source_project_id) && (
              <div className="mt-1 text-[11px] text-content-tertiary">
                project ·{' '}
                <span className="font-mono">
                  {chat.source_project_name ?? chat.source_project_id}
                </span>
              </div>
            )}
          </div>
        </div>
        <div className="text-[10px] text-content-tertiary">
          captured {chat.captured_at ?? '—'} · updated {chat.updated_at}
        </div>
      </div>

      {/* chats-v1 inbox: suggestions + manual move */}
      <div className="border-b border-border bg-amber-50/30 p-4">
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-amber-700">
            {inbox ? (
              <>
                <Inbox size={12} /> Inbox — suggest a destination
              </>
            ) : (
              <>
                <Lightbulb size={12} /> Reclassify or move
              </>
            )}
          </div>
          {!inbox && (
            <button
              type="button"
              onClick={() => setClassifyOpen((v) => !v)}
              className="rounded border border-border bg-white px-2 py-0.5 text-[10px] font-medium text-content-secondary hover:bg-surface-secondary"
            >
              {classifyOpen ? 'Hide suggestions' : 'Show suggestions'}
            </button>
          )}
        </div>

        {showSuggestions && (
          <div className="space-y-2">
            {classify.isLoading && (
              <div className="text-[11px] text-content-tertiary">Computing suggestions…</div>
            )}
            {classify.isError && (
              <div className="text-[11px] text-status-danger">
                Failed to load suggestions. {(classify.error as Error)?.message}
              </div>
            )}
            {classify.data && classify.data.suggestions.length === 0 && (
              <div className="text-[11px] text-content-tertiary">
                No existing namespaces to suggest yet. Type one below to create it.
              </div>
            )}
            {classify.data?.fallback && (
              <div className="text-[10px] text-content-tertiary">
                Embedding encoder unavailable — suggestions shown unranked.
              </div>
            )}
            {classify.data?.suggestions.map((s) => (
              <SuggestionPill
                key={s.namespace}
                namespace={s.namespace}
                similarity={s.similarity}
                signal={s.signal}
                memoryCount={s.memory_count}
                chatCount={s.chat_count}
                onMove={() => doMove(s.namespace)}
                disabled={moveMutation.isPending}
              />
            ))}

            <div className="mt-2 flex items-center gap-2">
              <input
                type="text"
                value={manualTarget}
                onChange={(e) => setManualTarget(e.target.value)}
                placeholder="…or type a namespace (e.g. project:steady-quill)"
                className="flex-1 rounded-md border border-border bg-white px-2 py-1.5 font-mono text-[11px] focus:border-brand-primary focus:outline-none"
              />
              <button
                type="button"
                onClick={() => manualTarget.trim() && doMove(manualTarget.trim())}
                disabled={moveMutation.isPending || !manualTarget.trim()}
                className="rounded-md bg-brand-primary px-2.5 py-1.5 text-[11px] font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                Move
              </button>
            </div>
            {moveMutation.isError && (
              <div className="mt-1 text-[10px] text-status-danger">
                {(moveMutation.error as Error)?.message ?? 'Failed to move chat.'}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {turns.length === 0 && (
          <div className="text-sm text-content-tertiary">No turns recorded yet.</div>
        )}
        {turns.map((turn) => (
          <ChatTurnView key={turn.turn_id} turn={turn} />
        ))}
      </div>
    </div>
  )
}
