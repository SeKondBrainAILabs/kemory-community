import { api } from './client'
import type {
  PermissionRuleResponse,
  PermissionRuleCreate,
  PermissionRuleUpdate,
  GatekeeperDecision,
  EvaluationRequest,
  ConsentRequestResponse,
} from './types'

export async function listPermissions(
  agentId?: string,
  scope?: string,
): Promise<PermissionRuleResponse[]> {
  const searchParams: Record<string, string> = {}
  if (agentId) searchParams.agent_id = agentId
  if (scope) searchParams.scope = scope
  return api.get('api/v1/permissions', { searchParams }).json()
}

export async function getPermission(ruleId: string): Promise<PermissionRuleResponse> {
  return api.get(`api/v1/permissions/${ruleId}`).json()
}

export async function createPermission(
  data: PermissionRuleCreate,
): Promise<PermissionRuleResponse> {
  return api.post('api/v1/permissions', { json: data }).json()
}

export async function updatePermission(
  ruleId: string,
  data: PermissionRuleUpdate,
): Promise<PermissionRuleResponse> {
  return api.put(`api/v1/permissions/${ruleId}`, { json: data }).json()
}

export async function deletePermission(ruleId: string): Promise<void> {
  await api.delete(`api/v1/permissions/${ruleId}`)
}

/**
 * KMV-QA-024: Toggle a permission rule's is_active state.
 * Uses the existing PUT endpoint with only the is_active field.
 */
export async function togglePermission(
  ruleId: string,
  isActive: boolean,
): Promise<PermissionRuleResponse> {
  return api.put(`api/v1/permissions/${ruleId}`, { json: { is_active: isActive } }).json()
}

export async function evaluateAccess(data: EvaluationRequest): Promise<GatekeeperDecision> {
  return api.post('api/v1/gatekeeper/evaluate', { json: data }).json()
}

/**
 * List JIT consent requests.
 *
 * Fix KMV-QA-006: Queries GET /api/v1/gatekeeper/consent which reads
 * directly from the ConsentRequest table instead of filtering audit logs.
 */
export async function listConsentRequests(
  status?: string,
): Promise<ConsentRequestResponse[]> {
  const searchParams: Record<string, string> = {}
  if (status) searchParams.status = status
  return api.get('api/v1/gatekeeper/consent', { searchParams }).json()
}

export async function resolveConsent(
  consentId: string,
  approved: boolean,
): Promise<GatekeeperDecision> {
  return api
    .post(`api/v1/gatekeeper/consent/${consentId}/resolve`, {
      searchParams: { approved: String(approved) },
    })
    .json()
}
