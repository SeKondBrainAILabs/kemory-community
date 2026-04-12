import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { RequireAuth } from '../RequireAuth'

// Mock useAuth
const mockUseAuth = vi.fn()
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}))

function renderWithRouter(
  ui: React.ReactElement,
  { initialEntries = ['/protected'] } = {},
) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/login" element={<div>Login Page</div>} />
        <Route path="/unauthorized" element={<div>Unauthorized Page</div>} />
        <Route path="/protected" element={ui} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RequireAuth', () => {
  beforeEach(() => {
    mockUseAuth.mockReset()
  })

  it('shows loading spinner while checking auth', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: true,
      hasRole: () => false,
      error: null,
    })

    renderWithRouter(
      <RequireAuth>
        <div>Protected Content</div>
      </RequireAuth>,
    )

    expect(screen.getByText('Checking authentication...')).toBeInTheDocument()
    expect(screen.queryByText('Protected Content')).not.toBeInTheDocument()
  })

  it('redirects to /login when not authenticated', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: false,
      hasRole: () => false,
      error: null,
    })

    renderWithRouter(
      <RequireAuth>
        <div>Protected Content</div>
      </RequireAuth>,
    )

    expect(screen.getByText('Login Page')).toBeInTheDocument()
    expect(screen.queryByText('Protected Content')).not.toBeInTheDocument()
  })

  it('renders children when authenticated with no role required', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      hasRole: () => true,
      error: null,
    })

    renderWithRouter(
      <RequireAuth>
        <div>Protected Content</div>
      </RequireAuth>,
    )

    expect(screen.getByText('Protected Content')).toBeInTheDocument()
  })

  it('renders children when authenticated with matching role', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      hasRole: (role: string) => role === 'super_admin',
      error: null,
    })

    renderWithRouter(
      <RequireAuth requiredRole="super_admin">
        <div>Admin Content</div>
      </RequireAuth>,
    )

    expect(screen.getByText('Admin Content')).toBeInTheDocument()
  })

  it('redirects to /unauthorized when missing required role', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      hasRole: () => false,
      error: null,
    })

    renderWithRouter(
      <RequireAuth requiredRole="super_admin">
        <div>Admin Content</div>
      </RequireAuth>,
    )

    expect(screen.getByText('Unauthorized Page')).toBeInTheDocument()
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument()
  })

  it('shows error message when auth error occurs', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: false,
      hasRole: () => false,
      error: 'Authentication service unavailable',
    })

    renderWithRouter(
      <RequireAuth>
        <div>Protected Content</div>
      </RequireAuth>,
    )

    expect(screen.getByText('Authentication Error')).toBeInTheDocument()
    expect(
      screen.getByText('Authentication service unavailable'),
    ).toBeInTheDocument()
  })
})
