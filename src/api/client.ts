import ky from 'ky'
import { getConfig, getToken } from '@/lib/keycloak'

const API_KEY_STORAGE_KEY = 's9nmv_api_key'

/** Check skip-auth from runtime config.json (preferred) or build-time env. */
function isSkipAuth(): boolean {
  const config = getConfig()
  if (config?.SKIP_AUTH === 'true') return true
  return import.meta.env.VITE_SKIP_AUTH === 'true'
}

/**
 * API key helpers — kept for agent-mode / dev fallback.
 * In production the dashboard uses Keycloak Bearer tokens.
 */
export function getApiKey(): string | null {
  return localStorage.getItem(API_KEY_STORAGE_KEY)
}

export function setApiKey(key: string) {
  localStorage.setItem(API_KEY_STORAGE_KEY, key)
}

export function clearApiKey() {
  localStorage.removeItem(API_KEY_STORAGE_KEY)
}

export const api = ky.create({
  prefixUrl: '/',
  timeout: 30_000,
  hooks: {
    beforeRequest: [
      (request) => {
        // 1. Keycloak Bearer token (production)
        if (!isSkipAuth()) {
          const token = getToken()
          if (token) {
            request.headers.set('Authorization', `Bearer ${token}`)
            return
          }
        }

        // 2. API key from localStorage or config.json (dev / agent mode)
        const apiKey = getApiKey() || getConfig()?.API_KEY || ''
        if (apiKey) {
          request.headers.set('X-API-Key', apiKey)
        }
      },
    ],
    afterResponse: [
      (_request, _options, response) => {
        if (response.status === 401) {
          clearApiKey()
        }
        return response
      },
    ],
  },
})
