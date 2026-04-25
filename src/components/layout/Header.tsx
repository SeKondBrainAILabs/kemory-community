import { useLocation } from 'react-router-dom'
import { LogOut, User, Code2 } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { useAdvancedView } from '@/contexts/AdvancedViewContext'
import { cn } from '@/lib/utils'

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
  
}

export function Header() {
  const location = useLocation()
  const { user, logout } = useAuth()
  const { advanced, toggle } = useAdvancedView()
  const basePath = '/' + (location.pathname.split('/')[1] ?? '')
  const title = pageTitles[basePath] ?? 'Kemory'

  return (
    <header className="flex h-16 items-center justify-between border-b border-black/[0.06] bg-white/50 px-6 backdrop-blur-[20px]">
      <h1 className="text-lg font-semibold text-content-primary">{title}</h1>

      <div className="flex items-center gap-3">
        {/* KMV-S15.1: Advanced view toggle (UUIDs, raw JSON, technical metadata) */}
        <button
          type="button"
          onClick={toggle}
          aria-pressed={advanced}
          title={advanced ? 'Switch to plain view' : 'Switch to advanced view'}
          className={cn(
            'flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors',
            advanced
              ? 'border-brand-primary/30 bg-brand-primary/10 text-brand-primary'
              : 'border-border bg-white/70 text-content-secondary hover:bg-surface-secondary',
          )}
        >
          <Code2 className="h-3.5 w-3.5" />
          {advanced ? 'Advanced' : 'Plain'}
        </button>
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
