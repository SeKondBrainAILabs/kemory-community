/**
 * Shared chat-detail content used by both the side-panel and the
 * standalone full-page deep link (/chats/:chatId).
 *
 * Self-contained — pass it a chatId and it handles the fetch +
 * loading/error states + render. No assumption about a "close"
 * affordance; the wrapper that owns the layout decides whether to
 * show a back button vs an X.
 */
import { useChat } from '@/hooks/useChats'
import { ChatTurnView } from '@/components/chats/ChatTurnView'
import { StatusBadge } from '@/components/shared/StatusBadge'

interface Props {
  chatId: string | null
}

export function ChatDetailPanel({ chatId }: Props) {
  const { data: chat, isLoading, isError, error } = useChat(chatId)

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
              <span>namespace · {chat.namespace}</span>
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
