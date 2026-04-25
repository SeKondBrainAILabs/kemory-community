/**
 * Authentication context for the Memory Vault dashboard.
 *
 * Supports two modes:
 * - Keycloak SSO (production): SKIP_AUTH is unset or false
 * - Dev mode: SKIP_AUTH=true bypasses Keycloak, uses synthetic user
 */
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import {
  initKeycloak,
  loadConfig,
  login,
  logout,
  getToken,
  getUser,
  hasRole,
  type KeycloakUser,
} from '@/lib/keycloak'

interface AuthState {
  user: KeycloakUser | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
  login: () => void
  logout: () => void
  getAccessToken: () => string | undefined
  hasRole: (role: string) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

const DEV_USER: KeycloakUser = {
  id: '00000000-0000-4000-8000-000000000001',
  username: 'dev-user',
  email: 'dev@localhost',
  firstName: 'Dev',
  lastName: 'User',
  roles: ['user', 'admin', 'super_admin', 'beta_approved'],
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<KeycloakUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [skipAuth, setSkipAuth] = useState(false)

  useEffect(() => {
    loadConfig()
      .then((config) => {
        const skip = config.SKIP_AUTH === 'true'
        setSkipAuth(skip)
        if (skip) {
          setUser(DEV_USER)
          setIsLoading(false)
          return
        }
        return initKeycloak()
      })
      .then((authenticated) => {
        if (authenticated) {
          setUser(getUser())
        }
        setIsLoading(false)
      })
      .catch((err) => {
        console.error('Auth init failed:', err)
        setError('Authentication service unavailable')
        setIsLoading(false)
      })
  }, [])

  const value: AuthState = {
    user,
    isAuthenticated: !!user,
    isLoading,
    error,
    login: () => login(),
    logout: () => {
      setUser(null)
      logout()
    },
    getAccessToken: () => (skipAuth ? 'dev-token' : getToken()),
    hasRole: (role: string) => {
      if (skipAuth) return true
      if (user) return user.roles.includes(role)
      return hasRole(role)
    },
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}
