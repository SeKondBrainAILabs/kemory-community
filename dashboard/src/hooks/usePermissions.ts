import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listPermissions,
  createPermission,
  updatePermission,
  deletePermission,
  togglePermission,
  listConsentRequests,
  resolveConsent,
} from '@/api/permissions'
import type { PermissionRuleCreate, PermissionRuleUpdate } from '@/api/types'

export function usePermissions(agentId?: string, scope?: string) {
  return useQuery({
    queryKey: ['permissions', agentId, scope],
    queryFn: () => listPermissions(agentId, scope),
  })
}

export function useCreatePermission() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: PermissionRuleCreate) => createPermission(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['permissions'] }),
  })
}

export function useUpdatePermission() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ ruleId, data }: { ruleId: string; data: PermissionRuleUpdate }) =>
      updatePermission(ruleId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['permissions'] }),
  })
}

export function useDeletePermission() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ruleId: string) => deletePermission(ruleId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['permissions'] }),
  })
}

/**
 * KMV-QA-024: Toggle a permission rule's is_active state.
 * Uses optimistic update for instant UI feedback.
 */
export function useTogglePermission() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ ruleId, isActive }: { ruleId: string; isActive: boolean }) =>
      togglePermission(ruleId, isActive),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['permissions'] }),
  })
}

/**
 * Fetch JIT consent requests directly from the ConsentRequest table.
 * Fix KMV-QA-006: Replaces the broken audit-log filtering approach.
 */
export function useConsentRequests(status?: string) {
  return useQuery({
    queryKey: ['consent', status ?? 'all'],
    queryFn: () => listConsentRequests(status),
    // Poll every 5 seconds to catch new JIT requests in real time
    refetchInterval: 5_000,
  })
}

export function useResolveConsent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ consentId, approved }: { consentId: string; approved: boolean }) =>
      resolveConsent(consentId, approved),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['consent'] })
      qc.invalidateQueries({ queryKey: ['audit'] })
    },
  })
}
