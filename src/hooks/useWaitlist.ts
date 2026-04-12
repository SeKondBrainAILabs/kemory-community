import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchWaitlistEntries,
  fetchWaitlistStats,
  approveUser,
  rejectUser,
  bulkApprove,
} from '@/api/waitlist'

/**
 * Fix KMV-QA-010: Use stable primitive query keys to prevent double-fetching.
 * Also adds retry:1 so a 403 (Keycloak admin role not assigned) fails fast
 * and surfaces an error state instead of a blank page.
 */
export function useWaitlistEntries(params: {
  service?: string
  status?: string
  limit?: number
  offset?: number
}) {
  return useQuery({
    queryKey: [
      'waitlist',
      'entries',
      params.service ?? 'all',
      params.status ?? 'all',
      params.limit ?? 100,
      params.offset ?? 0,
    ],
    queryFn: () => fetchWaitlistEntries(params),
    retry: 1,
  })
}

export function useWaitlistStats(service?: string) {
  return useQuery({
    queryKey: ['waitlist', 'stats', service ?? 'all'],
    queryFn: () => fetchWaitlistStats(service),
    retry: 1,
  })
}

export function useWaitlistAction() {
  const qc = useQueryClient()

  const approveMutation = useMutation({
    mutationFn: ({ userId, service }: { userId: string; service?: string }) =>
      approveUser(userId, service),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['waitlist'] }),
  })

  const rejectMutation = useMutation({
    mutationFn: ({ userId, service }: { userId: string; service?: string }) =>
      rejectUser(userId, service),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['waitlist'] }),
  })

  const bulkApproveMutation = useMutation({
    mutationFn: ({
      userIds,
      service,
    }: {
      userIds: string[]
      service?: string
    }) => bulkApprove(userIds, service),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['waitlist'] }),
  })

  return { approveMutation, rejectMutation, bulkApproveMutation }
}
