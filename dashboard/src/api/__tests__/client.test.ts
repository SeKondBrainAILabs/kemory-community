import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/runtimeConfig', () => ({
  getConfig: vi.fn(),
}))

import { getConfig } from '@/lib/runtimeConfig'
import { applyApiUrl } from '../client'

const mockedGetConfig = getConfig as unknown as ReturnType<typeof vi.fn>

describe('applyApiUrl', () => {
  afterEach(() => {
    mockedGetConfig.mockReset()
  })

  it('returns the original request when API_URL is not configured', () => {
    mockedGetConfig.mockReturnValue({
      API_KEY: 'local-key',
    })
    const req = new Request(`${window.location.origin}/api/v1/agents`)
    const out = applyApiUrl(req)
    expect(out.url).toBe(`${window.location.origin}/api/v1/agents`)
  })

  it('rewrites same-origin requests to the configured API_URL', () => {
    mockedGetConfig.mockReturnValue({
      API_KEY: 'local-key',
      API_URL: 'https://api.memory.example.com',
    })
    const req = new Request(`${window.location.origin}/api/v1/agents?status=active`)
    const out = applyApiUrl(req)
    expect(out.url).toBe('https://api.memory.example.com/api/v1/agents?status=active')
  })

  it('strips a trailing slash from API_URL before joining', () => {
    mockedGetConfig.mockReturnValue({
      API_KEY: 'local-key',
      API_URL: 'https://api.memory.example.com/',
    })
    const req = new Request(`${window.location.origin}/api/v1/agents`)
    const out = applyApiUrl(req)
    expect(out.url).toBe('https://api.memory.example.com/api/v1/agents')
  })

  it('leaves cross-origin requests untouched', () => {
    mockedGetConfig.mockReturnValue({
      API_KEY: 'local-key',
      API_URL: 'https://api.memory.example.com',
    })
    const req = new Request('https://other.example.com/something')
    const out = applyApiUrl(req)
    expect(out.url).toBe('https://other.example.com/something')
  })
})
