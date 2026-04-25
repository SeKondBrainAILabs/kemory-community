import { useQuery } from '@tanstack/react-query'
import { getAuditLogs, verifyChain, type AuditQueryParams } from '@/api/audit'

export function useAuditLogs(params: AuditQueryParams = {}) {
  return useQuery({
    queryKey: ['audit', 'logs', params],
    queryFn: () => getAuditLogs(params),
  })
}

export function useChainVerify(limit = 100) {
  return useQuery({
    queryKey: ['audit', 'verify', limit],
    queryFn: () => verifyChain(limit),
    enabled: false, // manual trigger only
  })
}
