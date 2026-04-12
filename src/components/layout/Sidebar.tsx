import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { useAuth } from '@/context/AuthContext'
import {
  LayoutDashboard,
  Bot,
  Heart,
  ScrollText,
  Shield,
  Database,
  Network,
  Bell,
  BarChart3,
  AlertTriangle,
  Users,
  Plug,
  ChevronLeft,
  ChevronRight,
  Brain,
} from 'lucide-react'

interface NavItem {
  to: string
  icon: typeof LayoutDashboard
  label: string
  requiredRole?: string
}

const navItems: NavItem[] = [
  { to: '/', icon: LayoutDashboard, label: 'Overview' },
  { to: '/agents', icon: Bot, label: 'Agents' },
  { to: '/system-health', icon: Heart, label: 'Health' },
  { to: '/audit', icon: ScrollText, label: 'Audit Log' },
  { to: '/permissions', icon: Shield, label: 'Permissions' },
  { to: '/memories', icon: Database, label: 'Memories' },
  { to: '/access', icon: Network, label: 'Access Map' },
  { to: '/consent', icon: Bell, label: 'Consent Queue' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/connectors', icon: Plug, label: 'Connectors' },
  { to: '/security', icon: AlertTriangle, label: 'Content Inspector', requiredRole: 'super_admin' },
  { to: '/waitlist', icon: Users, label: 'Waitlist', requiredRole: 'super_admin' },
]

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const { hasRole } = useAuth()

  const visibleItems = navItems.filter(
    (item) => !item.requiredRole || hasRole(item.requiredRole),
  )

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-border bg-white transition-all duration-200',
        collapsed ? 'w-[80px]' : 'w-[280px]',
      )}
    >
      {/* Logo */}
      <div className="flex h-16 items-center gap-3 border-b border-border px-4">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-primary text-white">
          <Brain size={20} />
        </div>
        {!collapsed && (
          <div className="overflow-hidden">
            <div className="text-sm font-semibold text-content-primary">S9N Memory Vault</div>
            <div className="text-xs text-content-tertiary">Control Plane</div>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
        {visibleItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-brand-primary/10 text-brand-primary'
                  : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
                collapsed && 'justify-center px-2',
              )
            }
          >
            <Icon size={20} className="shrink-0" />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex h-12 items-center justify-center border-t border-border text-content-tertiary hover:text-content-primary"
      >
        {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
      </button>
    </aside>
  )
}
