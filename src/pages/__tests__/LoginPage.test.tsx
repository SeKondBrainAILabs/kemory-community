import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { LoginPage } from '../LoginPage'

const mockUseAuth = vi.fn()
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}))

function renderLoginPage() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>Dashboard Home</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    mockUseAuth.mockReset()
  })

  it('renders sign-in button when not authenticated', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: false,
      error: null,
      login: vi.fn(),
    })

    renderLoginPage()

    expect(screen.getByText('Sign in')).toBeInTheDocument()
    expect(screen.getByText('S9N Memory Vault')).toBeInTheDocument()
  })

  it('redirects to / when already authenticated', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      error: null,
      login: vi.fn(),
    })

    renderLoginPage()

    expect(screen.getByText('Dashboard Home')).toBeInTheDocument()
  })

  it('shows error message when auth error is set', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: false,
      error: 'Authentication service unavailable',
      login: vi.fn(),
    })

    renderLoginPage()

    expect(
      screen.getByText('Authentication service unavailable'),
    ).toBeInTheDocument()
  })

  it('calls login when sign-in button is clicked', async () => {
    const mockLogin = vi.fn()
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: false,
      error: null,
      login: mockLogin,
    })

    renderLoginPage()

    await userEvent.click(screen.getByText('Sign in'))
    expect(mockLogin).toHaveBeenCalled()
  })

  it('shows loading spinner while auth is loading', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: true,
      error: null,
      login: vi.fn(),
    })

    renderLoginPage()

    expect(screen.queryByText('Sign in')).not.toBeInTheDocument()
  })
})
