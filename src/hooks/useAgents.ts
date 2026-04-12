import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listAgents, getAgent, registerAgent, approveAgent, suspendAgent, revokeAgent } from '@/api/agents'
import type { AgentRegistrationRequest } from '@/api/types'

export function useAgents(status?: string) {
  return useQuery({
    queryKey: ['agents', status],
    queryFn: () => listAgents(status),
  })
}

export function useAgent(agentId: string) {
  return useQuery({
    queryKey: ['agents', agentId],
    queryFn: () => getAgent(agentId),
    enabled: !!agentId,
  })
}

/**
 * BUG-003 fix: Mutation hook for registering a new agent.
 * Invalidates the agents list query on success so the new agent
 * appears immediately in the table.
 */
export function useRegisterAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: AgentRegistrationRequest) => registerAgent(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] })
    },
  })
}

export function useAgentAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId, action }: { agentId: string; action: 'approve' | 'suspend' | 'revoke' }) => {
      const fn = { approve: approveAgent, suspend: suspendAgent, revoke: revokeAgent }[action]
      return fn(agentId)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] })
    },
  })
}
