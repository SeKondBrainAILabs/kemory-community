import { api } from './client'
import type { AuditQueryResponse, ChainVerifyResult, RateLimitStatus } from './types'

export interface AuditQueryParams {
  agent_id?: string
  action?: string
  resource_type?: string
  outcome?: string
  // KMV-QA-018: Date range filters (ISO-8601 date strings, e.g. "2026-04-01")
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}

export async function getAuditLogs(params: AuditQueryParams = {}): Promise<AuditQueryResponse> {
  const searchParams: Record<string, string> = {}
  if (params.agent_id) searchParams.agent_id = params.agent_id
  if (params.action) searchParams.action = params.action
  if (params.resource_type) searchParams.resource_type = params.resource_type
  if (params.outcome) searchParams.outcome = params.outcome
  // KMV-QA-018: Pass date range to the backend (supported via the audit route fix in EPIC-001)
  if (params.date_from) searchParams.date_from = params.date_from
  if (params.date_to) searchParams.date_to = params.date_to
  if (params.limit) searchParams.limit = String(params.limit)
  if (params.offset) searchParams.offset = String(params.offset)
  return api.get('api/v1/audit/logs', { searchParams }).json()
}

export async function verifyChain(limit = 100): Promise<ChainVerifyResult> {
  return api.get('api/v1/audit/verify', { searchParams: { limit: String(limit) } }).json()
}

export async function getRateLimit(action = 'memory:write'): Promise<RateLimitStatus> {
  return api.get('api/v1/audit/rate-limit', { searchParams: { action } }).json()
}
