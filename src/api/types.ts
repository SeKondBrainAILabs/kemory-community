// ─── Agent Domain ────────────────────────────────────────────

export interface ScopeDeclaration {
  scope: string
  reason: string
}

export interface AgentRegistrationRequest {
  agent_name: string
  agent_description: string
  declared_scopes: ScopeDeclaration[]
  callback_url?: string
}

export interface AgentRegistrationResponse {
  agent_id: string
  agent_name: string
  status: string
  api_key: string
  declared_scopes: Record<string, unknown>[]
  message: string
}

export interface AgentResponse {
  agent_id: string
  agent_name: string
  agent_description: string
  status: 'pending' | 'pending_approval' | 'active' | 'suspended' | 'revoked'
  declared_scopes: Record<string, unknown>[]
  registered_at: string
  last_active_at: string | null
  total_reads: number
  total_writes: number
  denied_requests: number
}

// ─── Memory Domain ───────────────────────────────────────────

export interface MemoryCreate {
  namespace: string
  content: string
  content_type?: string
  metadata?: Record<string, unknown>
  ttl_seconds?: number
}

export interface MemoryUpdate {
  content?: string
  content_type?: string
  metadata?: Record<string, unknown>
  ttl_seconds?: number
}

export interface MemoryResponse {
  memory_id: string
  user_id: string
  namespace: string
  content: string
  content_type: string
  metadata: Record<string, unknown> | null
  source_agent_id: string | null
  source_type: string
  quality_score: number | null
  enrichment_status: string
  version: number
  ttl_seconds: number | null
  expires_at: string | null
  // Unified model fields (MV2-S01.3)
  session_id: string | null
  round_id: string | null
  valid_at: string | null
  invalid_at: string | null
  decay_score: number | null
  temporal_anchor: string | null
  created_at: string
  updated_at: string
}

export interface MemorySearchRequest {
  query?: string
  namespace?: string
  content_type?: string
  tags?: string[]
  limit?: number
  offset?: number
}

export interface MemoryListResponse {
  items: MemoryResponse[]
  total: number
  limit: number
  offset: number
}

export interface NamespaceInfo {
  namespace: string
  count: number
}

// ─── Permission Domain ───────────────────────────────────────

export const VALID_SCOPES = [
  'memory:read',
  'memory:write',
  'memory:delete',
  'namespace:read',
  'namespace:write',
  'namespace:create',
  'team:read',
  'team:write',
  'team:admin',
  'org:read',
  'graph:read',
  'graph:write',
  'admin:*',
] as const

export type ValidScope = (typeof VALID_SCOPES)[number]

export const VALID_ACTIONS = ['allow', 'deny', 'jit'] as const
export type ValidAction = (typeof VALID_ACTIONS)[number]

export interface PermissionRuleCreate {
  agent_id?: string | null
  scope: string
  action: ValidAction
  priority?: number
  namespace_filter?: string
  conditions?: Record<string, unknown>
}

export interface PermissionRuleUpdate {
  scope?: string
  action?: ValidAction
  priority?: number
  namespace_filter?: string
  conditions?: Record<string, unknown>
  is_active?: boolean
}

export interface PermissionRuleResponse {
  rule_id: string
  user_id: string
  agent_id: string | null
  scope: string
  action: ValidAction
  priority: number
  namespace_filter: string | null
  conditions: Record<string, unknown> | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface GatekeeperDecision {
  allowed: boolean
  outcome:
    | 'allowed'
    | 'denied'
    | 'jit_pending'
    | 'jit_approved'
    | 'jit_denied'
    | 'jit_timeout'
  matched_rule_id: string | null
  reason: string
  evaluation_time_ms: number | null
  consent_id: string | null
}

export interface EvaluationRequest {
  agent_id: string
  scope: string
  resource?: string
  namespace?: string
}

// ─── Audit Domain ────────────────────────────────────────────

export interface AuditEntry {
  audit_id: string
  user_id: string
  agent_id: string | null
  action: string
  resource_type: string
  resource_id: string | null
  namespace: string | null
  outcome: 'success' | 'denied' | 'error'
  details: Record<string, unknown> | null
  ip_address: string | null
  hash_chain: string
  created_at: string
}

export interface AuditQueryResponse {
  items: AuditEntry[]
  total: number
  limit: number
  offset: number
}

export interface RateLimitStatus {
  agent_id: string
  window_seconds: number
  max_requests: number
  current_count: number
  remaining: number
  reset_at: string
  is_limited: boolean
}

export interface ChainVerifyResult {
  status: string
  verified: number
  errors: string[]
}

// ─── Health Domain ───────────────────────────────────────────

export interface ServiceCheck {
  status: 'healthy' | 'unhealthy' | 'not_initialized'
  latency_ms?: number
  error?: string
}

export interface DeepHealthResponse {
  status: 'healthy' | 'degraded'
  service: string
  version: string
  environment: string
  checks: Record<string, ServiceCheck>
  timestamp: string
}

export interface LivenessResponse {
  status: string
  service: string
  version: string
  timestamp: string
}

// ─── Consent Domain ─────────────────────────────────────────
// Fix KMV-QA-006: Consent requests are now fetched directly from the
// ConsentRequest table via GET /api/v1/gatekeeper/consent.

export interface ConsentRequestResponse {
  consent_id: string
  user_id: string
  agent_id: string
  requested_scope: string
  requested_resource: string | null
  context: Record<string, unknown> | null
  status: 'pending' | 'approved' | 'denied' | 'timeout'
  created_at: string
  expires_at: string
  resolved_at: string | null
}

// ─── Security Domain ─────────────────────────────────────────
// Fix KMV-QA-009: Types now match actual backend response shapes.

export interface ScanRequest {
  content: string
}

/** Response from POST /api/v1/security/pii-scan */
export interface PIIScanResult {
  has_pii: boolean
  risk_level: 'none' | 'low' | 'medium' | 'high'
  detections: Array<{
    type: string
    value: string
    start: number
    end: number
    confidence: number
  }>
}

/** Response from POST /api/v1/security/injection-scan */
export interface InjectionScanResult {
  is_safe: boolean
  threats: Array<{
    type: string
    detail: string
    severity?: string
  }>
  sanitized_content: string
}

/** Response from POST /api/v1/security/scan (full scan) */
export interface FullScanResult {
  injection_scan: InjectionScanResult
  pii_scan: PIIScanResult
}

/** Union type for any scan result */
export type ScanResult = PIIScanResult | InjectionScanResult | FullScanResult

// ─── Enrichment Domain ───────────────────────────────────────

export interface EnrichmentResult {
  memory_id: string
  enrichment_status: string
  quality_score: number | null
  data: Record<string, unknown> | null
}
