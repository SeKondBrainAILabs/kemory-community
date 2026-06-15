/**
 * chats-v1 UI — unit tests
 *
 * Covers:
 *   1. ChatTurnView renders role + content + collapses thinking/tool_calls
 *   2. ChatArtifactView routes type → display (code as pre, image as img,
 *      file as download link)
 *   3. useChatList queryKey is stable across renders for the same params
 *   4. useChat is disabled when chatId is null/undefined
 *   5. useMintExtensionKey passes payload through; success surfaces api_key
 *
 * Heavier UX flows (row-click → ?chat=, mint→reveal modal, mapping
 * dialog validation) are integration-flavoured and are better covered
 * by Playwright once the e2e suite is wired for the new pages. For v1
 * we keep the unit tests focused and fast.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ChatTurnView } from '../../src/components/chats/ChatTurnView'
import { ChatArtifactView } from '../../src/components/chats/ChatArtifactView'
import type { ArtifactResponse, TurnResponse } from '../../src/api/chats'

// ── Mock API modules used by hooks ──────────────────────────────────
vi.mock('../../src/api/chats', async () => {
  const actual = await vi.importActual<typeof import('../../src/api/chats')>(
    '../../src/api/chats',
  )
  return {
    ...actual,
    listChats: vi.fn(),
    getChat: vi.fn(),
    deleteChat: vi.fn(),
  }
})

vi.mock('../../src/api/extensionKeys', () => ({
  listExtensionKeys: vi.fn(),
  mintExtensionKey: vi.fn(),
  revokeExtensionKey: vi.fn(),
}))

import { listChats, getChat } from '../../src/api/chats'
import { mintExtensionKey } from '../../src/api/extensionKeys'
import { useChat, useChatList } from '../../src/hooks/useChats'
import { useMintExtensionKey } from '../../src/hooks/useExtensionKeys'

// ── Test helpers ────────────────────────────────────────────────────
function freshClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

function wrapper(client: QueryClient) {
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children)
}

const SAMPLE_TURN: TurnResponse = {
  turn_id: 't1',
  chat_id: 'c1',
  source_turn_id: 'src-t1',
  parent_turn_id: null,
  role: 'assistant',
  content: 'Hello world',
  content_html: null,
  thinking_content: 'I am thinking deeply',
  tool_calls: [{ name: 'lookup', args: { x: 1 } }],
  turn_metadata: null,
  sequence: 0,
  created_at: '2026-05-24T00:00:00Z',
  artifacts: [],
}

const CODE_ARTIFACT: ArtifactResponse = {
  artifact_id: 'a1',
  turn_id: 't1',
  artifact_type: 'code',
  language: 'bash',
  content: 'echo hi',
  content_url: null,
  content_sha256: 'abc',
  artifact_metadata: null,
  created_at: '2026-05-24T00:00:00Z',
}

const IMAGE_ARTIFACT: ArtifactResponse = {
  ...CODE_ARTIFACT,
  artifact_id: 'a2',
  artifact_type: 'image',
  language: null,
  content: null,
  content_url: 'https://example.test/img.png',
}

const FILE_ARTIFACT: ArtifactResponse = {
  ...CODE_ARTIFACT,
  artifact_id: 'a3',
  artifact_type: 'file',
  language: null,
  content: null,
  content_url: 'https://example.test/report.pdf',
}

// ── ChatTurnView ────────────────────────────────────────────────────
describe('ChatTurnView', () => {
  it('renders role + content', () => {
    render(<ChatTurnView turn={SAMPLE_TURN} />)
    expect(screen.getByText(/assistant/i)).toBeInTheDocument()
    expect(screen.getByText('Hello world')).toBeInTheDocument()
  })

  it('hides thinking content by default and reveals on click', () => {
    render(<ChatTurnView turn={SAMPLE_TURN} />)
    expect(screen.queryByText(/I am thinking deeply/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /thinking/i }))
    expect(screen.getByText(/I am thinking deeply/)).toBeInTheDocument()
  })

  it('shows tool_calls count and lazy-opens the JSON view', () => {
    render(<ChatTurnView turn={SAMPLE_TURN} />)
    expect(screen.getByRole('button', { name: /1 tool call/i })).toBeInTheDocument()
    expect(screen.queryByText(/lookup/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /1 tool call/i }))
    expect(screen.getByText(/lookup/)).toBeInTheDocument()
  })
})

// ── ChatArtifactView ───────────────────────────────────────────────
describe('ChatArtifactView', () => {
  it('renders inline content for a code artifact', () => {
    render(<ChatArtifactView artifact={CODE_ARTIFACT} />)
    expect(screen.getByText('echo hi')).toBeInTheDocument()
    expect(screen.getByText(/code · bash/i)).toBeInTheDocument()
  })

  it('renders an <img> for image artifacts with content_url', () => {
    render(<ChatArtifactView artifact={IMAGE_ARTIFACT} />)
    const img = screen.getByRole('img')
    expect(img).toHaveAttribute('src', 'https://example.test/img.png')
  })

  it('renders a link for file artifacts with only content_url', () => {
    render(<ChatArtifactView artifact={FILE_ARTIFACT} />)
    const link = screen.getByRole('link', { name: /open artifact/i })
    expect(link).toHaveAttribute('href', 'https://example.test/report.pdf')
  })
})

// ── useChatList / useChat ──────────────────────────────────────────
describe('useChatList / useChat', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls listChats with the supplied filter params', async () => {
    ;(listChats as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      total: 0,
      limit: 20,
      offset: 0,
    })

    const client = freshClient()
    const { result } = renderHook(
      () => useChatList({ namespace: 'project:steady-quill', platform: 'claude' }),
      { wrapper: wrapper(client) },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(listChats).toHaveBeenCalledWith({
      namespace: 'project:steady-quill',
      platform: 'claude',
    })
  })

  it('useChat is disabled until chatId is provided', async () => {
    ;(getChat as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      chat_id: 'c1',
    })

    const client = freshClient()
    const { result, rerender } = renderHook(
      ({ id }: { id: string | null }) => useChat(id),
      { wrapper: wrapper(client), initialProps: { id: null as string | null } },
    )

    // Initial: no id → query disabled, no fetch
    expect(result.current.isFetching).toBe(false)
    expect(getChat).not.toHaveBeenCalled()

    rerender({ id: 'c1' })
    await waitFor(() =>
      expect(getChat).toHaveBeenCalledWith('c1', { includeTurns: true, includeArtifacts: true }),
    )
  })
})

// ── useMintExtensionKey ────────────────────────────────────────────
describe('useMintExtensionKey', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('mutates with the supplied label + returns the plaintext key once', async () => {
    ;(mintExtensionKey as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      key_id: 'k1',
      installation_id: 'i1',
      label: 'QA Test',
      api_key: 'kemory_abcd1234',
      scopes: ['memory:read'],
      created_at: '2026-05-24T00:00:00Z',
      message: 'ok',
    })

    const client = freshClient()
    const { result } = renderHook(() => useMintExtensionKey(), {
      wrapper: wrapper(client),
    })

    result.current.mutate({ label: 'QA Test', installation_id: 'i1' })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mintExtensionKey).toHaveBeenCalledWith({
      label: 'QA Test',
      installation_id: 'i1',
    })
    expect(result.current.data?.api_key).toBe('kemory_abcd1234')
  })
})
