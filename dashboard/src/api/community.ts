import { api } from './client'

export type CommunitySettings = {
  edition: string
  version: string
  user_id: string
  org_id?: string
  identity: string
  vector_backend: string
  blob_backend: string
  telemetry: string
  tenant_enforcement: string
  runtime: CommunityRuntimeSettings
}

export type CommunityLlmProvider = 'groq' | 'llama_cpp' | 'vertex'

export type CommunityRuntimeSettings = {
  llm_provider: CommunityLlmProvider
  llm_configured: boolean
  llm_api_key_configured: boolean
  llm_api_keys_configured: Record<CommunityLlmProvider, boolean>
  llm_model: string
  llm_base_url: string
  /** Compatibility fields retained for pre-release Community clients. */
  groq_configured: boolean
  groq_model: string
  openai_configured: boolean
  voyage_configured: boolean
  cohere_configured: boolean
  embedding_provider: 'fastembed' | 'openai' | 'voyage' | 'cohere'
  embedding_model: string
  artifact_max_bytes: number
  log_level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'
}

export type CommunityRuntimeSettingsUpdate = {
  llm_provider: CommunityLlmProvider
  llm_model: string
  llm_base_url: string
  llm_api_key?: string
  clear_llm_api_key?: boolean
  embedding_provider: CommunityRuntimeSettings['embedding_provider']
  embedding_model: string
  artifact_max_bytes: number
  log_level: CommunityRuntimeSettings['log_level']
  groq_api_key?: string
  clear_groq_api_key?: boolean
  openai_api_key?: string
  clear_openai_api_key?: boolean
  voyage_api_key?: string
  clear_voyage_api_key?: boolean
  cohere_api_key?: string
  clear_cohere_api_key?: boolean
}

export type CommunityLlmTestResult = {
  provider: CommunityLlmProvider
  model: string
  response: string
}

export type CommunityExport = {
  schema_version: number
  edition: string
  exported_at: string
  memories: Array<{
    namespace: string
    content: string
    content_type: string
    metadata?: Record<string, unknown>
    ttl_seconds?: number | null
    created_at?: string | null
    updated_at?: string | null
  }>
}

export async function getCommunitySettings(): Promise<CommunitySettings> {
  return api.get('api/v1/community/settings').json()
}

export async function updateCommunitySettings(
  update: CommunityRuntimeSettingsUpdate,
): Promise<CommunityRuntimeSettings> {
  return api.put('api/v1/community/settings', { json: update }).json()
}

export async function testCommunityLlm(
  settings: Pick<
    CommunityRuntimeSettingsUpdate,
    'llm_provider' | 'llm_model' | 'llm_base_url' | 'llm_api_key'
  >,
): Promise<CommunityLlmTestResult> {
  return api.post('api/v1/community/llm/test', { json: settings }).json()
}

export async function exportCommunityBundle(): Promise<CommunityExport> {
  return api.get('api/v1/community/export').json()
}

export async function importCommunityBundle(bundle: CommunityExport): Promise<{ imported: number }> {
  return api.post('api/v1/community/import', { json: { memories: bundle.memories ?? [] } }).json()
}
