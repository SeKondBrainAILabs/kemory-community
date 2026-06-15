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

/**
 * Rewrite a same-origin request to hit the API host configured at runtime.
 *
 * The dashboard is served from `app.memory.*` and the API lives at `api.memory.*`.
 * Default `prefixUrl: '/'` makes ky resolve calls to the dashboard origin, which
 * only works when an nginx / Vite proxy forwards `/api/*` upstream. When the
 * deployment doesn't have that proxy (or it can't reach the API container),
 * `config.json:API_URL` lets us point requests at the API host directly.
 */
export function applyApiUrl(request: Request): Request {
  const apiUrl = getConfig()?.API_URL
  if (!apiUrl) return request
  const url = new URL(request.url)
  if (url.origin !== window.location.origin) return request
  const base = apiUrl.replace(/\/$/, '')
  return new Request(`${base}${url.pathname}${url.search}`, request)
}

export const api = ky.create({
  prefixUrl: '/',
  timeout: 30_000,
  hooks: {
    beforeRequest: [
      (request) => {
        const rewritten = applyApiUrl(request)

        // 1. Keycloak Bearer token (production)
        if (!isSkipAuth()) {
          const token = getToken()
          if (token) {
            rewritten.headers.set('Authorization', `Bearer ${token}`)
            return rewritten
          }
        }

        // 2. API key from localStorage or config.json (dev / agent mode)
        const apiKey = getApiKey() || getConfig()?.API_KEY || ''
        if (apiKey) {
          rewritten.headers.set('X-API-Key', apiKey)
        }
        return rewritten
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
