/**
 * Community runtime auth shim.
 *
 * The community dashboard authenticates API calls with X-API-Key, either from
 * /config.json or from localStorage via the API client helpers. The exported
 * names intentionally match the hosted dashboard's old Keycloak service so the
 * surrounding React app keeps the same contract.
 */

interface RuntimeConfig {
  SKIP_AUTH: boolean | string
  API_KEY?: string
  API_URL?: string
}

export interface KeycloakUser {
  id: string
  username: string
  email: string
  firstName: string
  lastName: string
  roles: string[]
}

const COMMUNITY_USER: KeycloakUser = {
  id: '00000000-0000-4000-8000-000000000001',
  username: 'community-user',
  email: 'community@localhost',
  firstName: 'Community',
  lastName: 'User',
  roles: ['user', 'admin', 'super_admin', 'beta_approved'],
}

let _config: RuntimeConfig | null = null

export async function loadConfig(): Promise<RuntimeConfig> {
  if (_config) return _config
  try {
    const resp = await fetch('/config.json')
    if (resp.ok) {
      _config = await resp.json()
    }
  } catch {
    // Fallback below.
  }
  if (!_config) {
    _config = {
      SKIP_AUTH: import.meta.env.VITE_SKIP_AUTH ?? true,
      API_KEY: import.meta.env.VITE_KEMORY_API_KEY,
      API_URL: import.meta.env.VITE_API_URL,
    }
  }
  return _config
}

export function getConfig(): RuntimeConfig | null {
  return _config
}

export async function initKeycloak(): Promise<boolean> {
  await loadConfig()
  return true
}

export function login() {
  window.location.assign('/')
}

export function logout() {
  localStorage.removeItem('s9nmv_api_key')
  window.location.assign('/login')
}

export function getToken(): string | undefined {
  return undefined
}

export function getUserRoles(): string[] {
  return COMMUNITY_USER.roles
}

export function hasRole(role: string): boolean {
  return COMMUNITY_USER.roles.includes(role)
}

export function getUser(): KeycloakUser {
  return COMMUNITY_USER
}
