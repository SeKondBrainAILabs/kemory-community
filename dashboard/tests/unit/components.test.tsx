import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusBadge } from '../../src/components/shared/StatusBadge'
import { LoadingSkeleton, CardSkeleton } from '../../src/components/shared/LoadingSkeleton'

/**
 * Unit Tests: Shared Components
 *
 * Tests for the StatusBadge and LoadingSkeleton components.
 * These components are used across every page in the dashboard.
 */

describe('StatusBadge', () => {
  it('should render "active" status with correct text', () => {
    render(<StatusBadge status="active" />)
    expect(screen.getByText(/active/i)).toBeInTheDocument()
  })

  it('should render "pending" status', () => {
    render(<StatusBadge status="pending" />)
    expect(screen.getByText(/pending/i)).toBeInTheDocument()
  })

  it('should render "suspended" status', () => {
    render(<StatusBadge status="suspended" />)
    expect(screen.getByText(/suspended/i)).toBeInTheDocument()
  })

  it('should render "revoked" status', () => {
    render(<StatusBadge status="revoked" />)
    expect(screen.getByText(/revoked/i)).toBeInTheDocument()
  })

  it('should render "success" outcome', () => {
    render(<StatusBadge status="success" />)
    expect(screen.getByText(/success/i)).toBeInTheDocument()
  })

  it('should render "denied" outcome', () => {
    render(<StatusBadge status="denied" />)
    expect(screen.getByText(/denied/i)).toBeInTheDocument()
  })

  it('should render "error" outcome', () => {
    render(<StatusBadge status="error" />)
    expect(screen.getByText(/error/i)).toBeInTheDocument()
  })

  it('should render "healthy" status', () => {
    render(<StatusBadge status="healthy" />)
    expect(screen.getByText(/healthy/i)).toBeInTheDocument()
  })

  it('should render "degraded" status', () => {
    render(<StatusBadge status="degraded" />)
    expect(screen.getByText(/degraded/i)).toBeInTheDocument()
  })

  it('should render "unhealthy" status', () => {
    render(<StatusBadge status="unhealthy" />)
    expect(screen.getByText(/unhealthy/i)).toBeInTheDocument()
  })

  it('should render "jit_pending" status', () => {
    render(<StatusBadge status="jit_pending" />)
    expect(screen.getByText(/jit/i)).toBeInTheDocument()
  })

  it('should not throw for an unknown status', () => {
    expect(() => render(<StatusBadge status="unknown_status" />)).not.toThrow()
  })
})

describe('LoadingSkeleton', () => {
  it('should render the correct number of skeleton lines', () => {
    const { container } = render(<LoadingSkeleton lines={5} />)
    // Each line should be a skeleton element
    const skeletonElements = container.querySelectorAll('.skeleton')
    expect(skeletonElements.length).toBe(5)
  })

  it('should render with default lines when no prop is provided', () => {
    expect(() => render(<LoadingSkeleton />)).not.toThrow()
  })

  it('should render with 1 line', () => {
    expect(() => render(<LoadingSkeleton lines={1} />)).not.toThrow()
  })

  it('should render with 10 lines', () => {
    expect(() => render(<LoadingSkeleton lines={10} />)).not.toThrow()
  })
})

describe('CardSkeleton', () => {
  it('should render without throwing', () => {
    expect(() => render(<CardSkeleton />)).not.toThrow()
  })

  it('should render skeleton elements inside the card', () => {
    const { container } = render(<CardSkeleton />)
    const skeletonElements = container.querySelectorAll('.skeleton')
    expect(skeletonElements.length).toBeGreaterThanOrEqual(1)
  })
})
