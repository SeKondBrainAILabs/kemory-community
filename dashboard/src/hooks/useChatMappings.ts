/**
 * Kemory dashboard — Chat namespace mapping hooks (chats-v1 UI).
 *
 * Backed by /api/v1/chat-mappings. Mappings are small lists per user
 * (typically <20) so we don't paginate, just refetch on every mutation.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createMapping,
  deleteMapping,
  listMappings,
  updateMapping,
  type ChatMappingCreateRequest,
  type ChatMappingUpdateRequest,
} from '@/api/chatMappings'

export function useChatMappings() {
  return useQuery({
    queryKey: ['chat-mappings'],
    queryFn: listMappings,
    staleTime: 30_000,
  })
}

export function useCreateChatMapping() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ChatMappingCreateRequest) => createMapping(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['chat-mappings'] })
    },
  })
}

export function useUpdateChatMapping() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ mappingId, data }: { mappingId: string; data: ChatMappingUpdateRequest }) =>
      updateMapping(mappingId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['chat-mappings'] })
    },
  })
}

export function useDeleteChatMapping() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (mappingId: string) => deleteMapping(mappingId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['chat-mappings'] })
    },
  })
}
