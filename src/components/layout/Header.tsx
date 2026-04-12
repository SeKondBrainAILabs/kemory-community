import { useLocation } from 'react-router-dom'
import { LogOut, User } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'

const pageTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/agents': 'Agent Registry',
  '/health': 'System Health',
  '/audit': 'Audit Log',
  '/permissions': 'Permission Rules',
  '/memories': 'Memory Explorer',
  '/access': 'Access Map',
  '/consent': 'Consent Queue',
  '/analytics': 'Storage Analytics',
  '/connectors': 'Connectors',
  '/security': 'Security Alerts',
  '/waitlist': 'Waitlist Management',
}

export function Header() {
  const location = useLocation()
  const { user, logout } = useAuth()
  const basePath = '/' + (location.pathname.split('/')[1] ?? '')
  const title = pageTitles[basePath] ?? 'S9N Memory Vault'

  return (
    <header className="flex h-16 items-center justify-between border-b border-border bg-white px-6">
      <h1 className="text-lg font-semibold text-content-primary">{title}</h1>

      <div className="flex items-center gap-3">
        {user && (
          <>
            <div className="flex items-center gap-2 text-sm text-content-secondary">
              <User className="h-4 w-4" />
              <span>{user.firstName} {user.lastName}</span>
            </div>
            <button
              onClick={logout}
              className="flex items-center gap-1 rounded-md px-3 py-1.5 text-sm text-content-secondary hover:bg-surface-secondary transition-colors"
            >
              <LogOut className="h-4 w-4" />
              Sign out
            </button>
          </>
        )}
      </div>
    </header>
  )
}
