/**
 * Kemory dashboard — Artifacts React Query hooks (project files — v3.35.0).
 *
 * Covers namespace-level and memory-level artifacts.  Follows the same
 * patterns as useChats / useMemories: stable queryKeys, sane staleTime,
 * cache invalidation on mutate.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  deleteArtifact,
  listMemoryArtifacts,
  listNamespaceArtifacts,
  uploadArtifact,
  uploadMemoryArtifact,
  type UploadArtifactParams,
} from '@/api/artifacts'

// ─── List ──────────────────────────────────────────────────────────

export function useNamespaceArtifacts(
  namespace: string | null | undefined,
  params: { limit?: number; offset?: number } = {},
) {
  return useQuery({
    queryKey: ['artifacts', 'namespace', namespace ?? '', params.limit ?? 50, params.offset ?? 0],
    queryFn: () => listNamespaceArtifacts(namespace!, params),
    enabled: !!namespace,
    staleTime: 15_000,
    placeholderData: (prev) => prev,
  })
}

export function useMemoryArtifacts(memoryId: string | null | undefined) {
  return useQuery({
    queryKey: ['artifacts', 'memory', memoryId ?? ''],
    queryFn: () => listMemoryArtifacts(memoryId!),
    enabled: !!memoryId,
    staleTime: 30_000,
  })
}

// ─── Upload ────────────────────────────────────────────────────────

export function useUploadArtifact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (params: UploadArtifactParams) => uploadArtifact(params),
    onSuccess: (_data, variables) => {
      // Invalidate the namespace list so the file grid refreshes.
      if (variables.namespace) {
        qc.invalidateQueries({ queryKey: ['artifacts', 'namespace', variables.namespace] })
      }
      // Broader invalidation covers namespace-resolved cases.
      qc.invalidateQueries({ queryKey: ['artifacts', 'namespace'] })
    },
  })
}

export function useUploadMemoryArtifact(memoryId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => uploadMemoryArtifact(memoryId, file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['artifacts', 'memory', memoryId] })
    },
  })
}

// ─── Delete ────────────────────────────────────────────────────────

export function useDeleteArtifact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (artifactId: string) => deleteArtifact(artifactId),
    onSuccess: () => {
      // Invalidate all artifact lists — we don't know which namespace the
      // deleted artifact belonged to without a map lookup.
      qc.invalidateQueries({ queryKey: ['artifacts'] })
    },
  })
}
