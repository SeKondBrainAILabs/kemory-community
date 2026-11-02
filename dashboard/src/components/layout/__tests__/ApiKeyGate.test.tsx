import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { API_UNAUTHORIZED_EVENT, getApiKey, setApiKey } from '@/api/client'
import { ApiKeyGate } from '../ApiKeyGate'

function renderGate() {
  return render(
    <ApiKeyGate>
      <div>dashboard content</div>
    </ApiKeyGate>,
  )
}

describe('ApiKeyGate', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('asks for the key when none is stored', () => {
    renderGate()

    expect(screen.getByText('Enter your Kemory API key')).toBeInTheDocument()
    expect(screen.queryByText('dashboard content')).not.toBeInTheDocument()
  })

  it('stores a key the API accepts and shows the dashboard', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('[]', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    renderGate()

    await userEvent.type(screen.getByLabelText('API key'), 'good-key')
    await userEvent.click(screen.getByRole('button', { name: 'Unlock dashboard' }))

    expect(await screen.findByText('dashboard content')).toBeInTheDocument()
    expect(getApiKey()).toBe('good-key')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/namespaces', { headers: { 'X-API-Key': 'good-key' } })
  })

  it('keeps the prompt and stores nothing when the API rejects the key', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })))
    renderGate()

    await userEvent.type(screen.getByLabelText('API key'), 'bad-key')
    await userEvent.click(screen.getByRole('button', { name: 'Unlock dashboard' }))

    expect(await screen.findByText(/That key was rejected/)).toBeInTheDocument()
    expect(getApiKey()).toBeNull()
  })

  it('locks again when a later request is rejected', () => {
    setApiKey('stale-key')
    renderGate()
    expect(screen.getByText('dashboard content')).toBeInTheDocument()

    act(() => {
      window.dispatchEvent(new Event(API_UNAUTHORIZED_EVENT))
    })

    expect(screen.getByText('Enter your Kemory API key')).toBeInTheDocument()
  })
})
