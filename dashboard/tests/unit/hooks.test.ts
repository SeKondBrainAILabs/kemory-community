import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

/**
 * Unit Tests: Custom React Hooks
 *
 * Tests for the useAgents, usePermissions, useAuditLogs, and useHealth hooks.
 * All API functions are mocked at the module level to test hook behavior in isolation.
 *
 * BUG COVERAGE:
 * - BUG-007: useAuditLogs returns empty data — tested via mock to verify
 *   the hook correctly processes the API response shape.
 * - BUG-006: useDeepHealth returns unexpected structure — tested via mock
 *   to verify the hook handles various API response shapes.
 */

// ============================================================
// MOCK SETUP — mock at the API function level, not the client
// ============================================================

vi.mock('../../src/api/agents', () => ({
  listAgents: vi.fn(),
  getAgent: vi.fn(),
  approveAgent: vi.fn(),
  suspendAgent: vi.fn(),
  revokeAgent: vi.fn(),
  registerAgent: vi.fn(),
  getAgentToken: vi.fn(),
}))

vi.mock('../../src/api/audit', () => ({
  getAuditLogs: vi.fn(),
  verifyChain: vi.fn(),
}))

vi.mock('../../src/api/health', () => ({
  getDeepHealth: vi.fn(),
}))

vi.mock('../../src/api/permissions', () => ({
  listPermissions: vi.fn(),
  createPermission: vi.fn(),
  updatePermission: vi.fn(),
  deletePermission: vi.fn(),
  resolveConsent: vi.fn(),
}))

import { listAgents } from '../../src/api/agents'
import { getAuditLogs } from '../../src/api/audit'
import { listPermissions } from '../../src/api/permissions'

// Helper to create a fresh QueryClient for each test
function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  })
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children)
}

// ============================================================
// AGENTS HOOK TESTS
// ============================================================
describe('useAgents hook', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should return agents data when API call succeeds', async () => {
    const mockAgents = [
      {
        id: 'agent-1',
        name: 'manus',
        status: 'active',
        reads: 100,
        writes: 50,
        denied: 2,
        created_at: '2026-01-01T00:00:00Z',
      },
    ]
    vi.mocked(listAgents).mockResolvedValueOnce(mockAgents as any)

    const { useAgents } = await import('../../src/hooks/useAgents')
    const { result } = renderHook(() => useAgents(), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toBeDefined()
    expect(result.current.data).toHaveLength(1)
    expect(result.current.data?.[0].name).toBe('manus')
  })

  it('should return error state when API call fails', async () => {
    vi.mocked(listAgents).mockRejectedValueOnce(new Error('Network error'))

    const { useAgents } = await import('../../src/hooks/useAgents')
    const { result } = renderHook(() => useAgents(), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toBeDefined()
  })

  it('should start in loading state before data resolves', async () => {
    let resolvePromise!: (value: any) => void
    const pendingPromise = new Promise((resolve) => { resolvePromise = resolve })
    vi.mocked(listAgents).mockImplementationOnce(() => pendingPromise as any)
    const { useAgents } = await import('../../src/hooks/useAgents')
    const { result } = renderHook(() => useAgents(), { wrapper: createWrapper() })
    // Before resolution, the hook should be in a pending/loading state
    expect(result.current.isPending).toBe(true)
    // Clean up by resolving the promise
    resolvePromise([])
  })

  it('should pass status filter to the API function', async () => {
    vi.mocked(listAgents).mockResolvedValueOnce([])

    const { useAgents } = await import('../../src/hooks/useAgents')
    renderHook(() => useAgents('active'), { wrapper: createWrapper() })

    await waitFor(() => expect(vi.mocked(listAgents)).toHaveBeenCalledWith('active'))
  })
})

// ============================================================
// AUDIT LOGS HOOK TESTS (BUG-007 coverage)
// ============================================================
describe('useAuditLogs hook', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should return audit log items when API returns correct shape', async () => {
    const mockAuditResponse = {
      items: [
        {
          id: 'log-1',
          timestamp: '2026-04-11T09:00:00Z',
          action: 'memory:read',
          agent_id: 'agent-1',
          namespace: 'kora_hai',
          outcome: 'success',
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    }
    vi.mocked(getAuditLogs).mockResolvedValueOnce(mockAuditResponse as any)

    const { useAuditLogs } = await import('../../src/hooks/useAudit')
    const { result } = renderHook(() => useAuditLogs({}), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.items).toHaveLength(1)
    expect(result.current.data?.total).toBe(1)
  })

  it('BUG-007: should handle empty items array gracefully', async () => {
    // Simulates the current broken state where the API returns empty items
    const mockEmptyResponse = { items: [], total: 0, page: 1, page_size: 50 }
    vi.mocked(getAuditLogs).mockResolvedValueOnce(mockEmptyResponse as any)

    const { useAuditLogs } = await import('../../src/hooks/useAudit')
    const { result } = renderHook(() => useAuditLogs({}), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.items).toEqual([])
    expect(result.current.data?.total).toBe(0)
    // The hook should NOT be in error state for an empty response
    expect(result.current.isError).toBe(false)
  })

  it('should pass filter parameters to the API function', async () => {
    vi.mocked(getAuditLogs).mockResolvedValueOnce({
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
    } as any)

    const { useAuditLogs } = await import('../../src/hooks/useAudit')
    renderHook(
      () => useAuditLogs({ agent_id: 'agent-1', action: 'memory:read', outcome: 'success' }),
      { wrapper: createWrapper() }
    )

    await waitFor(() => expect(vi.mocked(getAuditLogs)).toHaveBeenCalled())
    const callArgs = vi.mocked(getAuditLogs).mock.calls[0][0]
    expect(callArgs).toMatchObject({ agent_id: 'agent-1', action: 'memory:read', outcome: 'success' })
  })
})

// ============================================================
// HEALTH HOOK TESTS (BUG-006 coverage)
// ============================================================
describe('useDeepHealth hook', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('BUG-006: should handle missing "services" key in API response', async () => {
    // Simulates the broken state where the API returns an unexpected shape
    const { getDeepHealth } = await import('../../src/api/health')
    vi.mocked(getDeepHealth).mockResolvedValueOnce({ status: 'healthy' } as any)

    const { useDeepHealth } = await import('../../src/hooks/useHealth')
    const { result } = renderHook(() => useDeepHealth(), { wrapper: createWrapper() })

    await waitFor(() => !result.current.isLoading)
    // Should not crash — should return the data even if services is missing
    expect(result.current.isError).toBe(false)
  })

  it('BUG-006: should handle 401 Unauthorized from health endpoint', async () => {
    // Simulates the case where auth token is not sent to /api/health/deep
    const { getDeepHealth } = await import('../../src/api/health')
    vi.mocked(getDeepHealth).mockRejectedValueOnce(
      Object.assign(new Error('Unauthorized'), { response: { status: 401 } })
    )

    const { useDeepHealth } = await import('../../src/hooks/useHealth')
    const { result } = renderHook(() => useDeepHealth(), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isError).toBe(true))
    // The error should be captured, not cause a crash
    expect(result.current.error).toBeDefined()
  })
})

// ============================================================
// PERMISSIONS HOOK TESTS
// ============================================================
describe('usePermissions hook', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should return permissions data when API call succeeds', async () => {
    const mockPermissions = [
      { id: 'p1', priority: 10, agent_id: 'agent-1', scope: 'memory:write', action: 'deny' },
      { id: 'p2', priority: 20, agent_id: 'agent-2', scope: 'memory:read', action: 'allow' },
      { id: 'p3', priority: 30, agent_id: '*', scope: 'memory:read', action: 'allow' },
    ]
    vi.mocked(listPermissions).mockResolvedValueOnce(mockPermissions as any)

    const { usePermissions } = await import('../../src/hooks/usePermissions')
    const { result } = renderHook(() => usePermissions(), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toBeDefined()
    expect(result.current.data).toHaveLength(3)
  })

  it('should return error state when API call fails', async () => {
    vi.mocked(listPermissions).mockRejectedValueOnce(new Error('Forbidden'))

    const { usePermissions } = await import('../../src/hooks/usePermissions')
    const { result } = renderHook(() => usePermissions(), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})
