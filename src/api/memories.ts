import { api } from './client'
import type {
  MemoryResponse,
  MemoryListResponse,
  MemorySearchRequest,
  NamespaceInfo,
  EnrichmentResult,
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
