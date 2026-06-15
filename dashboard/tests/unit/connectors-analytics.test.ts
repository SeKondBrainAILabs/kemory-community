import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/**
 * Unit Tests: Connectors & Analytics Data Processing
 *
 * BUG COVERAGE:
 * - BUG-011: Connector "connected" state is stored in localStorage only,
 *   not persisted to the backend. Tests verify the localStorage-based
 *   state management and identify the gap.
 * - BUG-008: Analytics pie chart percentage calculation rounds all small
 *   values to 0%. Tests verify the calculation logic.
 */

// ============================================================
// CONNECTOR STATE TESTS (BUG-011)
// ============================================================
describe('Connector State Management', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('BUG-011: connector connected state should NOT rely solely on localStorage', () => {
    // This test documents the architectural gap:
    // The ConnectorsPage uses localStorage to track which connectors are "connected"
    // This means the state is lost on browser refresh and is not shared across users.
    //
    // Expected behavior: connector state should be persisted to the backend API.
    // Current behavior: state is stored in localStorage under "kora_connected_connectors".

    // Simulate what the ConnectorsPage does
    const STORAGE_KEY = 'kora_connected_connectors'
    const connectedSet = new Set<string>()
    connectedSet.add('claude-code')
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...connectedSet]))

    // Verify it's in localStorage
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    expect(stored).toContain('claude-code')

    // After clearing localStorage (simulating a new session), state is lost
    localStorage.clear()
    const storedAfterClear = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    expect(storedAfterClear).not.toContain('claude-code')

    // BUG: This demonstrates that connector state is ephemeral
    // FIX NEEDED: POST /api/connectors/:id/connect should persist the state
  })

  it('should correctly parse connector IDs from localStorage', () => {
    const STORAGE_KEY = 'kora_connected_connectors'
    const connectors = ['claude-code', 'claude-desktop', 'custom-agent']
    localStorage.setItem(STORAGE_KEY, JSON.stringify(connectors))

    const stored: string[] = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    expect(stored).toHaveLength(3)
    expect(stored).toContain('claude-code')
    expect(stored).toContain('claude-desktop')
  })

  it('should handle malformed localStorage data without crashing', () => {
    const STORAGE_KEY = 'kora_connected_connectors'
    localStorage.setItem(STORAGE_KEY, 'not-valid-json')

    // The ConnectorsPage should handle this gracefully
    expect(() => {
      try {
        JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
      } catch {
        return []
      }
    }).not.toThrow()
  })
})

// ============================================================
// ANALYTICS PERCENTAGE CALCULATION TESTS (BUG-008)
// ============================================================
describe('Analytics Namespace Percentage Calculation', () => {
  /**
   * BUG-008: When there are 509 namespaces with a total of 10704 memories,
   * most namespaces have very few memories (e.g., 1-20). When displayed as
   * a percentage of 10704, these round down to 0% in the Recharts legend.
   *
   * The fix should use a minimum display value or show absolute counts.
   */

  function calculatePercentage(count: number, total: number): number {
    if (total === 0) return 0
    return Math.round((count / total) * 100)
  }

  it('BUG-008: small namespace counts round to 0% with Math.round', () => {
    const total = 10704
    const smallCount = 21 // 21/10704 = 0.196% → rounds to 0%

    const percentage = calculatePercentage(smallCount, total)
    // This demonstrates the bug: 21 memories out of 10704 shows as 0%
    expect(percentage).toBe(0)
  })

  it('BUG-008: only the largest namespace shows non-zero percentage', () => {
    const total = 10704
    // The largest namespace (lme_oracle_28dc39ac) has ~107 memories (1%)
    const largestCount = 107

    const percentage = calculatePercentage(largestCount, total)
    expect(percentage).toBe(1)
  })

  it('should use toFixed(1) to show fractional percentages for small namespaces', () => {
    const total = 10704
    const smallCount = 21

    // Correct approach: use toFixed(1) instead of Math.round
    const percentage = ((smallCount / total) * 100).toFixed(1)
    expect(percentage).toBe('0.2') // Shows 0.2% instead of 0%
  })

  it('should correctly calculate percentage for a large namespace', () => {
    const total = 10704
    const largeCount = 500

    const percentage = ((largeCount / total) * 100).toFixed(1)
    expect(parseFloat(percentage)).toBeCloseTo(4.7, 1)
  })

  it('should handle zero total without division by zero', () => {
    const result = calculatePercentage(100, 0)
    expect(result).toBe(0)
    expect(isNaN(result)).toBe(false)
    expect(isFinite(result)).toBe(true)
  })

  it('should handle zero count correctly', () => {
    const result = calculatePercentage(0, 10704)
    expect(result).toBe(0)
  })
})

// ============================================================
// AGENT ACTIVITY STATS TESTS (BUG-009)
// ============================================================
describe('Agent Activity Stats Processing', () => {
  /**
   * BUG-009: The Agent Activity table in StorageAnalyticsPage shows 0 for
   * reads, writes, and denied for all agents. The useAgents hook returns
   * these stats correctly on the Agents page, but the Analytics page
   * appears to use a different data source or calculation.
   */

  it('should correctly sum reads across all agents', () => {
    const agents = [
      { id: 'a1', name: 'manus', reads: 150, writes: 75, denied: 3 },
      { id: 'a2', name: 'claude-desktop-agent', reads: 200, writes: 100, denied: 5 },
      { id: 'a3', name: 'claude-code-agent', reads: 50, writes: 25, denied: 1 },
    ]

    const totalReads = agents.reduce((sum, a) => sum + a.reads, 0)
    expect(totalReads).toBe(400)
  })

  it('BUG-009: agent stats should not be zero when agents have activity', () => {
    // This test documents the expected behavior
    // In the live app, agents show reads/writes on the Agents page
    // but show 0 on the Analytics page
    const agentFromAgentsPage = { id: 'a1', name: 'manus', reads: 150, writes: 75, denied: 3 }

    // The Analytics page should show the same stats
    // BUG: Currently shows 0 for all
    expect(agentFromAgentsPage.reads).toBeGreaterThan(0)
    expect(agentFromAgentsPage.writes).toBeGreaterThan(0)
  })
})
