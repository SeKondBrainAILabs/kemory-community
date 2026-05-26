/**
 * Kemory dashboard — AI Chats API client (chats-v1 UI).
 *
 * Wraps the v3.31.0 REST endpoints under /api/v1/chats. The Kanvas
 * Chrome Extension writes; the dashboard reads. Auth is the existing
 * Bearer-token path on the shared ky client (see ./client.ts).
 *
 * Backend reference: backend/api/routes/ai_chats.py
 * Schemas mirror backend/services/ai_chat_service.py response models.
 */
import { api } from './client'

// ─── Shared types ───────────────────────────────────────────────────

export type Platform = 'chatgpt' | 'claude' | 'gemini' | 'manus' | 'other'
export type Role = 'user' | 'assistant' | 'system' | 'tool'
export type ArtifactType =
  | 'code'
  | 'image'
  | 'file'
  | 'react'
  | 'html'
  | 'svg'
  | 'audio' // chats-v1 v3.33.0
  | 'video' // chats-v1 v3.33.0

export interface ArtifactResponse {
  artifact_id: string
  turn_id: string
  artifact_type: ArtifactType
  language: string | null
  content: string | null
  content_url: string | null
  content_sha256: string
  artifact_metadata: Record<string, unknown> | null
  created_at: string
}

export interface TurnResponse {
  turn_id: string
  chat_id: string
  source_turn_id: string | null
  parent_turn_id: string | null
  role: Role
  content: string
  content_html: string | null
  thinking_content: string | null
  tool_calls: Array<Record<string, unknown>> | null
  turn_metadata: Record<string, unknown> | null
  sequence: number
  created_at: string
  artifacts: ArtifactResponse[]
}

export interface ChatResponse {
  chat_id: string
  user_id: string
  platform: Platform
  platform_conversation_id: string
  source_project_id: string | null
  source_project_name: string | null
  namespace: string
  requested_namespace: string | null
  title: string | null
  model: string | null
  chat_metadata: Record<string, unknown> | null
  content_hash: string
  captured_at: string | null
  source_type: string
  installation_id: string | null
  created_at: string
  updated_at: string
  turn_count: number
  was_created: boolean
  was_updated: boolean
  turns: TurnResponse[] | null
}

export interface ChatListItem {
  chat_id: string
  platform: Platform
  platform_conversation_id: string
  namespace: string
  title: string | null
  captured_at: string | null
  updated_at: string
  turn_count: number
  artifact_count: number
}

export interface ChatListResponse {
  items: ChatListItem[]
  total: number
  limit: number
  offset: number
}

export interface ChatListParams {
  namespace?: string
  platform?: Platform
  since?: string // ISO-8601
  limit?: number
  offset?: number
}

// ─── Calls ──────────────────────────────────────────────────────────

export async function listChats(params: ChatListParams = {}): Promise<ChatListResponse> {
  // ky's searchParams stringifies primitives; strip undefined to avoid
  // empty-string filters landing on the backend (which would no-op
  // anyway, but cleaner request URLs are easier to debug).
  const search: Record<string, string | number> = {}
  if (params.namespace) search.namespace = params.namespace
  if (params.platform) search.platform = params.platform
  if (params.since) search.since = params.since
  search.limit = params.limit ?? 20
  search.offset = params.offset ?? 0
  return api.get('api/v1/chats', { searchParams: search }).json()
}

export async function getChat(
  chatId: string,
  options: { includeTurns?: boolean; includeArtifacts?: boolean } = {},
): Promise<ChatResponse> {
  // Backend's `include` is a comma-separated list. Asking for artifacts
  // implies turns server-side, but we send the explicit list for clarity.
  const parts: string[] = []
  if (options.includeTurns || options.includeArtifacts) parts.push('turns')
  if (options.includeArtifacts) parts.push('artifacts')
  const search = parts.length ? { include: parts.join(',') } : undefined
  return api.get(`api/v1/chats/${encodeURIComponent(chatId)}`, { searchParams: search }).json()
}

export async function deleteChat(chatId: string): Promise<void> {
  await api.delete(`api/v1/chats/${encodeURIComponent(chatId)}`)
}

// ─── Classify + Move (chats-v1 inbox) ───────────────────────────────

export interface NamespaceSuggestion {
  namespace: string
  similarity: number
  signal: 'summary' | 'description' | 'name'
  memory_count: number
  chat_count: number
}

export interface ChatClassifyResponse {
  chat_id: string
  current_namespace: string
  in_inbox: boolean
  sample_chars: number
  suggestions: NamespaceSuggestion[]
  fallback: boolean
}

/** True when the namespace string is one of the per-platform inboxes. */
export function isInboxNamespace(ns: string | null | undefined): boolean {
  return typeof ns === 'string' && ns.startsWith('kora:inbox:')
}

export async function classifyChat(
  chatId: string,
  limit = 5,
): Promise<ChatClassifyResponse> {
  return api
    .post(`api/v1/chats/${encodeURIComponent(chatId)}/classify`, {
      searchParams: { limit },
    })
    .json()
}

export interface ChatMoveRequest {
  namespace: string
  allow_duplicate?: boolean
}

export async function moveChat(
  chatId: string,
  data: ChatMoveRequest,
): Promise<ChatResponse> {
  return api
    .post(`api/v1/chats/${encodeURIComponent(chatId)}/move`, { json: data })
    .json()
}
