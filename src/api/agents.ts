import { api } from './client'
import type { AgentResponse, AgentRegistrationRequest, AgentRegistrationResponse } from './types'

export async function listAgents(status?: string): Promise<AgentResponse[]> {
  const searchParams = status ? { status } : undefined
  return api.get('api/v1/agents', { searchParams }).json()
}

export async function getAgent(agentId: string): Promise<AgentResponse> {
  return api.get(`api/v1/agents/${agentId}`).json()
}

export async function registerAgent(data: AgentRegistrationRequest): Promise<AgentRegistrationResponse> {
  return api.post('api/v1/agents', { json: data }).json()
}

export async function approveAgent(agentId: string): Promise<AgentResponse> {
  return api.post(`api/v1/agents/${agentId}/approve`).json()
}

export async function suspendAgent(agentId: string): Promise<AgentResponse> {
  return api.post(`api/v1/agents/${agentId}/suspend`).json()
}

export async function revokeAgent(agentId: string): Promise<AgentResponse> {
  return api.post(`api/v1/agents/${agentId}/revoke`).json()
}

export async function getAgentToken(agentId: string) {
  return api.post(`api/v1/agents/${agentId}/token`).json<{
    access_token: string
    token_type: string
    expires_in: number
    agent_id: string
    scopes: string[]
  }>()
}
