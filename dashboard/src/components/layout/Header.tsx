import { useLocation } from 'react-router-dom'
import { User, Code2, Menu } from 'lucide-react'
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
  '/settings': 'Settings',

}

export function Header({ onMenuClick }: { onMenuClick?: () => void }) {
  const location = useLocation()
  const { advanced, toggle } = useAdvancedView()
  const basePath = '/' + (location.pathname.split('/')[1] ?? '')
  const title = pageTitles[basePath] ?? 'Kemory'

  return (
    <header className="flex h-16 items-center justify-between border-b border-black/[0.06] bg-white/50 px-4 backdrop-blur-[20px] sm:px-6">
      <div className="flex min-w-0 items-center gap-2">
        {/* S9N-6167: mobile hamburger — opens the sidebar drawer */}
        <button
          type="button"
          onClick={onMenuClick}
          aria-label="Open navigation"
          className="-ml-1 rounded-lg p-2 text-content-secondary hover:bg-surface-secondary md:hidden"
        >
          <Menu className="h-5 w-5" />
        </button>
        <h1 className="truncate text-lg font-semibold text-content-primary">{title}</h1>
      </div>

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
        <div className="hidden items-center gap-2 text-sm text-content-secondary sm:flex">
          <User className="h-4 w-4" />
          <span>Local user</span>
        </div>
      </div>
    </header>
  )
}
