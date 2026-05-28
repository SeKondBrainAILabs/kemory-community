import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/keycloak', () => ({
  getConfig: vi.fn(),
  getToken: vi.fn(() => undefined),
}))

import { getConfig } from '@/lib/keycloak'
import { applyApiUrl } from '../client'

const mockedGetConfig = getConfig as unknown as ReturnType<typeof vi.fn>

describe('applyApiUrl', () => {
  afterEach(() => {
    mockedGetConfig.mockReset()
  })

  it('returns the original request when API_URL is not configured', () => {
    mockedGetConfig.mockReturnValue({
      KEYCLOAK_URL: '/auth',
      KEYCLOAK_REALM: 'r',
      KEYCLOAK_CLIENT_ID: 'c',
      SKIP_AUTH: 'true',
    })
    const req = new Request(`${window.location.origin}/api/v1/agents`)
    const out = applyApiUrl(req)
    expect(out.url).toBe(`${window.location.origin}/api/v1/agents`)
  })

  it('rewrites same-origin requests to the configured API_URL', () => {
    mockedGetConfig.mockReturnValue({
      KEYCLOAK_URL: '/auth',
      KEYCLOAK_REALM: 'r',
      KEYCLOAK_CLIENT_ID: 'c',
      SKIP_AUTH: 'true',
      API_URL: 'https://api.memory.example.com',
    })
    const req = new Request(`${window.location.origin}/api/v1/agents?status=active`)
    const out = applyApiUrl(req)
    expect(out.url).toBe('https://api.memory.example.com/api/v1/agents?status=active')
  })

  it('strips a trailing slash from API_URL before joining', () => {
    mockedGetConfig.mockReturnValue({
      KEYCLOAK_URL: '/auth',
      KEYCLOAK_REALM: 'r',
      KEYCLOAK_CLIENT_ID: 'c',
      SKIP_AUTH: 'true',
      API_URL: 'https://api.memory.example.com/',
    })
    const req = new Request(`${window.location.origin}/api/v1/agents`)
    const out = applyApiUrl(req)
    expect(out.url).toBe('https://api.memory.example.com/api/v1/agents')
  })

  it('leaves cross-origin requests untouched', () => {
    mockedGetConfig.mockReturnValue({
      KEYCLOAK_URL: '/auth',
      KEYCLOAK_REALM: 'r',
      KEYCLOAK_CLIENT_ID: 'c',
      SKIP_AUTH: 'true',
      API_URL: 'https://api.memory.example.com',
    })
    const req = new Request('https://other.example.com/something')
    const out = applyApiUrl(req)
    expect(out.url).toBe('https://other.example.com/something')
  })
})
