import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { Sidebar } from '../Sidebar'

const mockUseAuth = vi.fn()
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}))

function renderSidebar() {
  return render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>,
  )
}

describe('Sidebar', () => {
  beforeEach(() => {
    mockUseAuth.mockReset()
  })

  it('shows all nav items for super_admin', () => {
    mockUseAuth.mockReturnValue({
      hasRole: () => true,
    })

    renderSidebar()

    expect(screen.getByText('Overview')).toBeInTheDocument()
    expect(screen.getByText('Agents')).toBeInTheDocument()
    expect(screen.getByText('Security')).toBeInTheDocument()
    expect(screen.getByText('Waitlist')).toBeInTheDocument()
  })

  it('hides restricted items for regular user', () => {
    mockUseAuth.mockReturnValue({
      hasRole: () => false,
    })

    renderSidebar()

    expect(screen.getByText('Overview')).toBeInTheDocument()
    expect(screen.getByText('Agents')).toBeInTheDocument()
    expect(screen.queryByText('Security')).not.toBeInTheDocument()
    expect(screen.queryByText('Waitlist')).not.toBeInTheDocument()
  })

  it('shows non-restricted items regardless of role', () => {
    mockUseAuth.mockReturnValue({
      hasRole: () => false,
    })

    renderSidebar()

    const expectedItems = [
      'Overview',
      'Agents',
      'Health',
      'Audit Log',
      'Permissions',
      'Memories',
      'Access Map',
      'Consent Queue',
      'Analytics',
    ]

    for (const item of expectedItems) {
      expect(screen.getByText(item)).toBeInTheDocument()
    }
  })
})
