/**
 * Kemory dashboard — Chats React Query hooks (chats-v1 UI).
 *
 * Mirrors the useMemories pattern: stable primitive queryKeys so React
 * Query dedupes across renders; sane staleTime so list ↔ detail
 * navigation doesn't refetch on every click.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  deleteChat,
  getChat,
  listChats,
  type ChatListParams,
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
