import { useQuery } from '@tanstack/react-query'
import { getDeepHealth } from '@/api/health'

export function useDeepHealth() {
  return useQuery({
    queryKey: ['health', 'deep'],
    queryFn: getDeepHealth,
    refetchInterval: 30_000,
  })
}
