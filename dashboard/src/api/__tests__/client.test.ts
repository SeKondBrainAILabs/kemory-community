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

  it('returns the original request when API_URL is not configured', async () => {
    mockedGetConfig.mockReturnValue({
      API_KEY: 'local-key',
    })
    const req = new Request(`${window.location.origin}/api/v1/agents`)
    const out = await applyApiUrl(req)
    expect(out.url).toBe(`${window.location.origin}/api/v1/agents`)
  })

  it('rewrites same-origin requests to the configured API_URL', async () => {
    mockedGetConfig.mockReturnValue({
      API_KEY: 'local-key',
      API_URL: 'https://api.memory.example.com',
    })
    const req = new Request(`${window.location.origin}/api/v1/agents?status=active`)
    const out = await applyApiUrl(req)
    expect(out.url).toBe('https://api.memory.example.com/api/v1/agents?status=active')
  })

  it('strips a trailing slash from API_URL before joining', async () => {
    mockedGetConfig.mockReturnValue({
      API_KEY: 'local-key',
      API_URL: 'https://api.memory.example.com/',
    })
    const req = new Request(`${window.location.origin}/api/v1/agents`)
    const out = await applyApiUrl(req)
    expect(out.url).toBe('https://api.memory.example.com/api/v1/agents')
  })

  it('leaves cross-origin requests untouched', async () => {
    mockedGetConfig.mockReturnValue({
      API_KEY: 'local-key',
      API_URL: 'https://api.memory.example.com',
    })
    const req = new Request('https://other.example.com/something')
    const out = await applyApiUrl(req)
    expect(out.url).toBe('https://other.example.com/something')
  })

  it('carries a POST body over as buffered bytes', async () => {
    mockedGetConfig.mockReturnValue({
      API_URL: 'http://127.0.0.1:8111',
    })
    const req = new Request(`${window.location.origin}/api/v1/memories/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': 'local-key' },
      body: JSON.stringify({ query: 'vector' }),
    })
    const out = await applyApiUrl(req)
    expect(out.url).toBe('http://127.0.0.1:8111/api/v1/memories/search')
    expect(out.method).toBe('POST')
    expect(out.headers.get('X-API-Key')).toBe('local-key')
    expect(await out.text()).toBe('{"query":"vector"}')
  })
})
