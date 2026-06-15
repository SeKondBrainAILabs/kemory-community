/**
 * Kemory dashboard — Chats React Query hooks (chats-v1 UI).
 *
 * Mirrors the useMemories pattern: stable primitive queryKeys so React
 * Query dedupes across renders; sane staleTime so list ↔ detail
 * navigation doesn't refetch on every click.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  classifyChat,
  deleteChat,
  getChat,
  listChats,
  moveChat,
  type ChatListParams,
  type ChatMoveRequest,
} from '@/api/chats'

export function useChatList(params: ChatListParams = {}) {
  return useQuery({
    queryKey: [
      'chats',
      'list',
      params.namespace ?? '',
      params.platform ?? '',
      params.since ?? '',
      params.limit ?? 20,
      params.offset ?? 0,
    ],
    queryFn: () => listChats(params),
    // Chats don't change rapidly — 15s avoids refetch on every filter
    // toggle while still surfacing new pushes from the extension within
    // a reasonable window.
    staleTime: 15_000,
    placeholderData: (prev) => prev,
  })
}

export function useChat(chatId: string | null | undefined, includeArtifacts = true) {
  return useQuery({
    queryKey: ['chats', chatId ?? '', includeArtifacts ? 'full' : 'turns'],
    queryFn: () =>
      getChat(chatId!, { includeTurns: true, includeArtifacts }),
    enabled: !!chatId,
    staleTime: 30_000,
  })
}

export function useDeleteChat() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (chatId: string) => deleteChat(chatId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['chats', 'list'] })
    },
  })
}

// chats-v1 inbox: classify + move. The classify call is a pure read
// (no caching needed beyond a short staleTime since suggestions can
// shift as more memories/chats accumulate). The move call invalidates
// the list + the per-chat detail.
export function useClassifyChat(chatId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ['chats', chatId ?? '', 'classify'],
    queryFn: () => classifyChat(chatId!),
    enabled: !!chatId && enabled,
    staleTime: 30_000,
  })
}

export function useMoveChat() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ chatId, data }: { chatId: string; data: ChatMoveRequest }) =>
      moveChat(chatId, data),
    onSuccess: (_res, { chatId }) => {
      qc.invalidateQueries({ queryKey: ['chats', 'list'] })
      qc.invalidateQueries({ queryKey: ['chats', chatId] })
      qc.invalidateQueries({ queryKey: ['chats', chatId, 'classify'] })
    },
  })
}
