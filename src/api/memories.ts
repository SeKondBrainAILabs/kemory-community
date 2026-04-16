import { api } from './client'
import type {
  MemoryResponse,
  MemoryListResponse,
  MemorySearchRequest,
  NamespaceInfo,
  EnrichmentResult,
  AccessMapResponse,
} from './types'

// EPIC-002: Memory CRUD request types (mirrors backend MemoryUpdate model)
export interface MemoryUpdateRequest {
  content?: string
  content_type?: string
  metadata?: Record<string, unknown>
  ttl_seconds?: number
}

export async function searchMemories(params: MemorySearchRequest): Promise<MemoryListResponse> {
  return api.post('api/v1/memories/search', { json: params }).json()
}

export async function getMemory(memoryId: string): Promise<MemoryResponse> {
  return api.get(`api/v1/memories/${memoryId}`).json()
}

export async function getNamespaces(): Promise<NamespaceInfo[]> {
  return api.get('api/v1/namespaces').json()
}

export async function getMemoryEnrichment(memoryId: string): Promise<EnrichmentResult> {
  return api.get(`api/v1/memories/${memoryId}/enrichment`).json()
}

// EPIC-002: KMV-QA-013 — Delete memory (soft-delete via backend)
export async function deleteMemory(memoryId: string): Promise<void> {
  await api.delete(`api/v1/memories/${memoryId}`)
}

// EPIC-002: KMV-QA-014 — Update memory content/type/metadata
export async function updateMemory(
  memoryId: string,
  data: MemoryUpdateRequest,
): Promise<MemoryResponse> {
  return api.put(`api/v1/memories/${memoryId}`, { json: data }).json()
}

// F12: Access Graph — agent-memory-namespace relationship graph
export async function getAccessMap(): Promise<AccessMapResponse> {
  return api.get('api/v1/graph/access-map').json()
}

// ─── Consolidation API (KMV-E14) ─────────────────────────────────────────────

export interface NamespacePolicy {
  namespace: string
  decay_rate: number
  retention_days: number
  auto_consolidate: boolean
  consolidation_hour_utc?: number
  description?: string
  is_default?: boolean
}

export interface ConsolidationStats {
  pending: number
  consolidating: number
  archived: number
  avg_weight: Record<string, number>
}

export interface ConsolidationSummary {
  status: string
  summary: {
    epoch_date: string
    namespace: string
    weight_decay: Record<string, unknown>
    auto_archived: Record<string, unknown>
    consolidated: Record<string, unknown>
    errors: string[]
  }
}

export async function triggerConsolidation(namespace: string): Promise<ConsolidationSummary> {
  return api.post(`api/v1/namespaces/${namespace}/consolidate`).json()
}

export async function getConsolidationStats(namespace: string): Promise<{ namespace: string; stats: Record<string, ConsolidationStats> }> {
  return api.get(`api/v1/namespaces/${namespace}/consolidation-stats`).json()
}

export async function getAllConsolidationStats(): Promise<{ stats: Record<string, Record<string, ConsolidationStats>> }> {
  return api.get('api/v1/namespaces/consolidation-stats').json()
}

export async function getNamespacePolicy(namespace: string): Promise<NamespacePolicy> {
  return api.get(`api/v1/namespaces/${namespace}/policy`).json()
}

export async function updateNamespacePolicy(
  namespace: string,
  policy: Partial<Omit<NamespacePolicy, 'namespace' | 'is_default'>>,
): Promise<NamespacePolicy> {
  return api.put(`api/v1/namespaces/${namespace}/policy`, { json: policy }).json()
}
