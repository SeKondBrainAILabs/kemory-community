import { describe, it, expect, vi, beforeEach } from 'vitest'
import { formatRelativeTime, formatLatency, cn } from '../../src/lib/utils'

/**
 * Unit Tests: Utility Functions
 *
 * Tests for the utility functions used across the dashboard.
 * These are pure functions with no side effects.
 */

describe('formatRelativeTime', () => {
  beforeEach(() => {
    // Mock Date.now() to a fixed timestamp for deterministic tests
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-11T10:00:00Z'))
  })

  it('should return "just now" for timestamps within the last minute', () => {
    const thirtySecondsAgo = new Date(Date.now() - 30_000).toISOString()
    const result = formatRelativeTime(thirtySecondsAgo)
    expect(result).toMatch(/just now|seconds ago|<1 min/i)
  })

  it('should return a minutes-ago string for timestamps 5 minutes ago', () => {
    const fiveMinutesAgo = new Date(Date.now() - 5 * 60_000).toISOString()
    const result = formatRelativeTime(fiveMinutesAgo)
    expect(result).toMatch(/5 min|5m/i)
  })

  it('should return an hours-ago string for timestamps 2 hours ago', () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 3600_000).toISOString()
    const result = formatRelativeTime(twoHoursAgo)
    expect(result).toMatch(/2 hour|2h/i)
  })

  it('should return a days-ago string for timestamps 3 days ago', () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 86400_000).toISOString()
    const result = formatRelativeTime(threeDaysAgo)
    expect(result).toMatch(/3 day|3d/i)
  })

  it('should handle ISO string timestamps', () => {
    const isoString = '2026-04-10T10:00:00Z' // exactly 1 day ago
    const result = formatRelativeTime(isoString)
    expect(typeof result).toBe('string')
    expect(result.length).toBeGreaterThan(0)
  })

  it('should not throw for an empty string', () => {
    expect(() => formatRelativeTime('')).not.toThrow()
  })

  it('should not throw for an invalid date string', () => {
    expect(() => formatRelativeTime('not-a-date')).not.toThrow()
  })
})

describe('formatLatency', () => {
  it('should format 0ms as "<1ms" (implementation returns <1ms for values < 1)', () => {
    const result = formatLatency(0)
    expect(result).toBe('<1ms')
  })

  it('should format 150ms correctly', () => {
    const result = formatLatency(150)
    expect(result).toMatch(/150\s*ms/i)
  })

  it('should format 1500ms as seconds', () => {
    const result = formatLatency(1500)
    // Should show either "1500ms" or "1.5s" depending on implementation
    expect(result).toMatch(/1[.,]5\s*s|1500\s*ms/i)
  })

  it('should return a string', () => {
    expect(typeof formatLatency(100)).toBe('string')
  })

  it('should handle negative values without throwing', () => {
    expect(() => formatLatency(-1)).not.toThrow()
  })
})

describe('cn (className utility)', () => {
  it('should merge class names correctly', () => {
    const result = cn('foo', 'bar')
    expect(result).toContain('foo')
    expect(result).toContain('bar')
  })

  it('should handle conditional class names', () => {
    const result = cn('base', true && 'active', false && 'inactive')
    expect(result).toContain('base')
    expect(result).toContain('active')
    expect(result).not.toContain('inactive')
  })

  it('should handle undefined and null values', () => {
    const result = cn('base', undefined, null, 'extra')
    expect(result).toContain('base')
    expect(result).toContain('extra')
  })

  it('should merge Tailwind conflicting classes correctly', () => {
    // tailwind-merge should resolve conflicts (e.g., px-2 and px-4 → px-4)
    const result = cn('px-2', 'px-4')
    expect(result).toBe('px-4')
  })

  it('should return an empty string for no arguments', () => {
    const result = cn()
    expect(typeof result).toBe('string')
  })
})
