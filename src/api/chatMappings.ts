/**
 * Kemory dashboard — Chat namespace mappings API (chats-v1 UI).
 *
 * Mappings let the user collapse multiple (platform, source project)
 * combinations onto one Kemory namespace. Many-to-one is by design
 * (multiple rows with the same `target_namespace`).
 *
 * Backend reference: backend/api/routes/chat_mappings.py
 *                    backend/services/ai_chat_service.py
 *                    (ChatMappingCreate / Update / Response)
 */
import { api } from './client'
import type { Platform } from './chats'

export interface ChatMappingResponse {
  mapping_id: string
  platform: Platform
  source_project_id: string | null
  source_project_name_pattern: string | null
  target_namespace: string
  priority: number
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface ChatMappingCreateRequest {
  platform: Platform
  source_project_id?: string | null
  source_project_name_pattern?: string | null
  target_namespace: string
  priority?: number
  enabled?: boolean
}

export interface ChatMappingUpdateRequest {
  target_namespace?: string
  priority?: number
  enabled?: boolean
  source_project_id?: string | null
  source_project_name_pattern?: string | null
}

export async function listMappings(): Promise<ChatMappingResponse[]> {
  return api.get('api/v1/chat-mappings').json()
}

export async function createMapping(
  data: ChatMappingCreateRequest,
): Promise<ChatMappingResponse> {
  return api.post('api/v1/chat-mappings', { json: data }).json()
}

export async function updateMapping(
  mappingId: string,
  data: ChatMappingUpdateRequest,
): Promise<ChatMappingResponse> {
  return api.patch(`api/v1/chat-mappings/${encodeURIComponent(mappingId)}`, { json: data }).json()
}

export async function deleteMapping(mappingId: string): Promise<void> {
  await api.delete(`api/v1/chat-mappings/${encodeURIComponent(mappingId)}`)
}
