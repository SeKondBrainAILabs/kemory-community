import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AuthProvider, useAuth } from '../AuthContext'

// Mock keycloak module
const mockLoadConfig = vi.fn()
const mockInitKeycloak = vi.fn()
const mockLogin = vi.fn()
const mockLogout = vi.fn()
const mockGetToken = vi.fn()
const mockGetUser = vi.fn()
const mockHasRole = vi.fn()

vi.mock('@/lib/keycloak', () => ({
  loadConfig: () => mockLoadConfig(),
  initKeycloak: () => mockInitKeycloak(),
  login: (...args: unknown[]) => mockLogin(...args),
  logout: () => mockLogout(),
  getToken: () => mockGetToken(),
  getUser: () => mockGetUser(),
  hasRole: (role: string) => mockHasRole(role),
}))

function TestConsumer() {
  const auth = useAuth()
  return (
    <div>
      <div data-testid="loading">{String(auth.isLoading)}</div>
      <div data-testid="authenticated">{String(auth.isAuthenticated)}</div>
      <div data-testid="error">{auth.error ?? 'none'}</div>
      <div data-testid="user">{auth.user?.username ?? 'none'}</div>
      <div data-testid="has-admin">{String(auth.hasRole('super_admin'))}</div>
      <div data-testid="token">{auth.getAccessToken() ?? 'none'}</div>
      <button onClick={auth.login}>Login</button>
      <button onClick={auth.logout}>Logout</button>
    </div>
  )
}

describe('AuthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('sets DEV_USER when SKIP_AUTH is true', async () => {
    mockLoadConfig.mockResolvedValue({ SKIP_AUTH: 'true' })

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })

    expect(screen.getByTestId('authenticated')).toHaveTextContent('true')
    expect(screen.getByTestId('user')).toHaveTextContent('dev-user')
    expect(screen.getByTestId('has-admin')).toHaveTextContent('true')
    expect(screen.getByTestId('token')).toHaveTextContent('dev-token')
  })

  it('authenticates via Keycloak when init succeeds', async () => {
    mockLoadConfig.mockResolvedValue({ SKIP_AUTH: 'false' })
    mockInitKeycloak.mockResolvedValue(true)
    mockGetUser.mockReturnValue({
      id: 'user-1',
      username: 'testuser',
      email: 'test@example.com',
      firstName: 'Test',
      lastName: 'User',
      roles: ['user', 'admin'],
    })

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })

    expect(screen.getByTestId('authenticated')).toHaveTextContent('true')
    expect(screen.getByTestId('user')).toHaveTextContent('testuser')
  })

  it('sets error when Keycloak init fails', async () => {
    mockLoadConfig.mockResolvedValue({ SKIP_AUTH: 'false' })
    mockInitKeycloak.mockRejectedValue(new Error('Keycloak init timed out'))

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })

    expect(screen.getByTestId('authenticated')).toHaveTextContent('false')
    expect(screen.getByTestId('error')).toHaveTextContent(
      'Authentication service unavailable',
    )
  })

  it('hasRole checks user roles array', async () => {
    mockLoadConfig.mockResolvedValue({ SKIP_AUTH: 'false' })
    mockInitKeycloak.mockResolvedValue(true)
    mockGetUser.mockReturnValue({
      id: 'user-1',
      username: 'regular',
      email: 'regular@example.com',
      firstName: 'Regular',
      lastName: 'User',
      roles: ['user'],
    })
    mockHasRole.mockReturnValue(false)

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })

    expect(screen.getByTestId('has-admin')).toHaveTextContent('false')
  })

  it('logout clears the user', async () => {
    mockLoadConfig.mockResolvedValue({ SKIP_AUTH: 'false' })
    mockInitKeycloak.mockResolvedValue(true)
    mockGetUser.mockReturnValue({
      id: 'user-1',
      username: 'testuser',
      email: 'test@example.com',
      firstName: 'Test',
      lastName: 'User',
      roles: ['user'],
    })

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('true')
    })

    await act(async () => {
      await userEvent.click(screen.getByText('Logout'))
    })

    expect(screen.getByTestId('authenticated')).toHaveTextContent('false')
    expect(mockLogout).toHaveBeenCalled()
  })

  it('throws when useAuth is used outside AuthProvider', () => {
    // Suppress console.error for this test
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

    expect(() => render(<TestConsumer />)).toThrow(
      'useAuth must be used within <AuthProvider>',
    )

    spy.mockRestore()
  })
})
