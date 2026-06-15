/**
 * Kemory dashboard — Extension API keys (chats-v1 UI).
 *
 * Mint / list / revoke per-install API keys for the Kanvas Chrome
 * Extension. The mint response carries the plaintext key exactly once.
 *
 * Backend reference: backend/api/routes/extension_keys.py
 *                    backend/services/extension_key_service.py
 *
 * Under the hood extension installs are AgentRegistry rows with
 * agent_kind='extension'. The auth path is unchanged; only the
 * mint/list/revoke endpoints are dedicated.
 */
import { api } from './client'

export interface ExtensionKeyInfo {
  key_id: string
  label: string
  installation_id: string | null
  scopes: string[]
  status: string  // 'active' | 'suspended' | 'revoked' | 'pending_approval'
  last_used_at: string | null
  created_at: string
}

export interface ExtensionKeyMintRequest {
  label: string
  installation_id?: string | null
  scopes?: string[]
}

export interface ExtensionKeyMintResponse {
  key_id: string
  installation_id: string | null
  label: string
  api_key: string  // plaintext — shown ONCE, never persisted in cleartext server-side
  scopes: string[]
  created_at: string
  message: string
}

export async function listExtensionKeys(): Promise<ExtensionKeyInfo[]> {
  return api.get('api/v1/extension/keys').json()
}

export async function mintExtensionKey(
  data: ExtensionKeyMintRequest,
): Promise<ExtensionKeyMintResponse> {
  return api.post('api/v1/extension/keys', { json: data }).json()
}

export async function revokeExtensionKey(keyId: string): Promise<void> {
  await api.delete(`api/v1/extension/keys/${encodeURIComponent(keyId)}`)
}
