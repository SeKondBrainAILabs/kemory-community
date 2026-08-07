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

export type CommunityRuntimeSettings = {
  groq_configured: boolean
  embedding_provider: 'fastembed' | 'openai' | 'voyage' | 'cohere'
  embedding_model: string
  groq_model: string
  artifact_max_bytes: number
  log_level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'
}

export type CommunityRuntimeSettingsUpdate = Omit<CommunityRuntimeSettings, 'groq_configured'> & {
  groq_api_key?: string
  clear_groq_api_key?: boolean
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

export async function exportCommunityBundle(): Promise<CommunityExport> {
  return api.get('api/v1/community/export').json()
}

export async function importCommunityBundle(bundle: CommunityExport): Promise<{ imported: number }> {
  return api.post('api/v1/community/import', { json: { memories: bundle.memories ?? [] } }).json()
}
