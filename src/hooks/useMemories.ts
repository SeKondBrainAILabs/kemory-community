/**
 * Memory Vault — Memory React Query Hooks
 *
 * Fix KMV-QA-004: Replaced object reference in queryKey with stable
 * primitive values derived from the params object.  Using the entire
 * params object as a queryKey caused React Query to treat every render
 * as a new cache entry (object identity !== structural equality) which
 * resulted in duplicate fetch calls and duplicate rows in the DataTable.
 *
 * EPIC-002 KMV-QA-013/014: Added useDeleteMemory and useUpdateMemory
 * mutations so the MemoryExplorerPage can delete and edit memories.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  searchMemories,
  getMemory,
  getNamespaces,
  getMemoryEnrichment,
  deleteMemory,
  updateMemory,
} from '@/api/memories'
import type { MemoryUpdateRequest } from '@/api/memories'
import type { MemorySearchRequest } from '@/api/types'

export function useMemorySearch(params: MemorySearchRequest) {
  // Stable queryKey: spread individual primitive values so React Query
  // can correctly deduplicate requests across renders.
  return useQuery({
    queryKey: [
      'memories',
      'search',
      params.query ?? '',
      params.namespace ?? '',
      params.content_type ?? '',
      params.limit ?? 50,
      params.offset ?? 0,
    ],
    queryFn: () => searchMemories(params),
    // Keep previous data while new results load to avoid table flicker
    placeholderData: (prev) => prev,
  })
}

export function useMemory(memoryId: string) {
  return useQuery({
    queryKey: ['memories', memoryId],
    queryFn: () => getMemory(memoryId),
    enabled: !!memoryId,
  })
}

export function useNamespaces() {
  return useQuery({
    queryKey: ['namespaces'],
    queryFn: getNamespaces,
    // Namespaces change infrequently — cache for 60 seconds
    staleTime: 60_000,
  })
}

export function useMemoryEnrichment(memoryId: string) {
  return useQuery({
    queryKey: ['memories', memoryId, 'enrichment'],
    queryFn: () => getMemoryEnrichment(memoryId),
    enabled: !!memoryId,
  })
}

// EPIC-002: KMV-QA-013 — Delete memory mutation
export function useDeleteMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (memoryId: string) => deleteMemory(memoryId),
    onSuccess: () => {
      // Invalidate all memory search queries so the table refreshes
      qc.invalidateQueries({ queryKey: ['memories', 'search'] })
      qc.invalidateQueries({ queryKey: ['namespaces'] })
    },
  })
}

// EPIC-002: KMV-QA-014 — Update memory mutation
export function useUpdateMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ memoryId, data }: { memoryId: string; data: MemoryUpdateRequest }) =>
      updateMemory(memoryId, data),
    onSuccess: (_result, { memoryId }) => {
      // Invalidate the specific memory and all search results
      qc.invalidateQueries({ queryKey: ['memories', memoryId] })
      qc.invalidateQueries({ queryKey: ['memories', 'search'] })
    },
  })
}
