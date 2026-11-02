import ky from 'ky'
import { getConfig } from '@/lib/runtimeConfig'

const API_KEY_STORAGE_KEY = 's9nmv_api_key'

/** Dispatched on window when the API rejects the key, so ApiKeyGate can ask again. */
export const API_UNAUTHORIZED_EVENT = 'kemory:unauthorized'

/**
 * API key helpers for community local_single_user auth.
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
 *
 * The body is buffered rather than carried over: `new Request(url, request)`
 * turns it into a stream, and Chrome only sends streamed bodies over HTTP/2,
 * so every POST to the plain-HTTP local API failed with
 * ERR_ALPN_NEGOTIATION_FAILED.
 */
export async function applyApiUrl(request: Request): Promise<Request> {
  const apiUrl = getConfig()?.API_URL
  if (!apiUrl) return request
  const url = new URL(request.url)
  if (url.origin !== window.location.origin) return request
  const base = apiUrl.replace(/\/$/, '')
  return new Request(`${base}${url.pathname}${url.search}`, {
    method: request.method,
    headers: request.headers,
    body: request.body ? await request.arrayBuffer() : undefined,
    signal: request.signal,
    credentials: request.credentials,
    cache: request.cache,
    redirect: request.redirect,
  })
}

export const api = ky.create({
  prefixUrl: '/',
  timeout: 30_000,
  hooks: {
    beforeRequest: [
      async (request) => {
        const rewritten = await applyApiUrl(request)

        // Community authentication is API-key only.
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
          window.dispatchEvent(new Event(API_UNAUTHORIZED_EVENT))
        }
        return response
      },
    ],
  },
})
