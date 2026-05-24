import { NavLink } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import {
  Brain,
  LayoutDashboard,
  Bot,
  Database,
  FolderTree,
  Heart,
  ScrollText,
  Shield,
  Network,
  Bell,
  BarChart3,
  AlertTriangle,
  Plug,
  GitGraph,
  Settings,
  MessageCircle,
  // chats-v1
  MessagesSquare,
  Link as LinkIcon,
  Smartphone,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { getLiveness } from '@/api/health'
import { cn } from '@/lib/utils'
import { useAuth } from '@/context/AuthContext'

declare const __FE_VERSION__: string

/**
 * Kemory inner sidebar.
 *
 * This is the active SekondBrain app's OWN navigation. It sits to the
 * right of the outer SekondBrainRail (app switcher). Layout / styling
 * mirrors the Pulse reference:
 *   - App header with logo, name, subtitle & version block.
 *   - Grouped nav links with label + icon.
 *   - Settings + Feedback at the bottom.
 *
 * Routes match the post-rebrand baseline (Kemory): /system-health,
 * /access-graph, /connectors, etc. Role-gated items hide for users
 * without the required role.
 */

type NavItem = {
  to: string
  icon: LucideIcon
  label: string
  requiredRole?: string
}

// Primary: the Kemory core workspaces.
// (Operations & ops items live in opsNav below — keeps primary/secondary split.)
// Waitlist is intentionally absent — removed in feat(rebrand-phase-2).
const primaryNav: NavItem[] = [
  { to: '/', icon: LayoutDashboard, label: 'Overview' },
  { to: '/memories', icon: Database, label: 'Memories' },
  // chats-v1: raw conversation capture (Kanvas Chrome Extension)
  { to: '/chats', icon: MessagesSquare, label: 'Chats' },
  { to: '/namespaces', icon: FolderTree, label: 'Namespaces' },
  { to: '/agents', icon: Bot, label: 'Agents' },
  { to: '/access', icon: Network, label: 'Access Map' },
]

// chats-v1: chat-related operations live in opsNav (settings-ish surfaces).
const chatsOpsNav: NavItem[] = [
  { to: '/chat-mappings', icon: LinkIcon, label: 'Chat Mappings' },
  { to: '/devices', icon: Smartphone, label: 'Devices' },
]

// Operations / control plane (matches post-rebrand baseline routes).
const opsNav: NavItem[] = [
  { to: '/system-health', icon: Heart, label: 'Health' },
  { to: '/permissions', icon: Shield, label: 'Permissions' },
  { to: '/consent', icon: Bell, label: 'Consent Queue' },
  { to: '/audit', icon: ScrollText, label: 'Audit Log' },
  { to: '/access-graph', icon: GitGraph, label: 'Access Graph' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/connectors', icon: Plug, label: 'Connectors' },
  // chats-v1 ops surfaces, slotted next to Connectors so they sit
  // together in the "things you wire up once" pile.
  ...chatsOpsNav,
  {
    to: '/security',
    icon: AlertTriangle,
    label: 'Content Inspector',
    requiredRole: 'super_admin',
  },
]

function NavRow({ to, icon: Icon, label }: NavItem) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors',
          isActive
            ? 'bg-white text-content-primary shadow-[0_1px_2px_rgba(0,0,0,0.04)] ring-1 ring-black/[0.04]'
            : 'text-content-secondary hover:bg-black/[0.04] hover:text-content-primary',
        )
      }
    >
      <Icon size={16} className="shrink-0" />
      <span className="truncate">{label}</span>
    </NavLink>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
      {children}
    </div>
  )
}

export function Sidebar() {
  const { hasRole } = useAuth()
  const { data: liveness } = useQuery({ queryKey: ['health-live'], queryFn: getLiveness, staleTime: 60_000 })
  const visibleOps = opsNav.filter(
    (item) => !item.requiredRole || hasRole(item.requiredRole),
  )

  return (
    <aside
      aria-label="Kemory"
      className="fixed left-[56px] top-0 z-40 flex h-screen w-[240px] flex-col border-r border-black/[0.06] bg-white/60 backdrop-blur-[20px]"
    >
      {/* App header: Kemory app tile + name + version block */}
      <div className="flex items-start gap-3 border-b border-black/[0.05] px-4 pb-4 pt-5">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] bg-gradient-to-br from-[#6366f1] to-[#8b5cf6] text-white shadow-sm">
          <Brain size={20} strokeWidth={2} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[15px] font-semibold leading-tight text-content-primary">
            Kemory
          </div>
          <div className="mt-0.5 text-[11px] leading-tight text-content-tertiary">
            by SekondBrain AI
          </div>
          <div className="mt-1.5 font-mono text-[10px] leading-tight text-content-tertiary/80">
            FE:{__FE_VERSION__} / BE:{liveness?.version ?? '…'}
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        <div className="space-y-0.5">
          {primaryNav.map((item) => (
            <NavRow key={item.to} {...item} />
          ))}
        </div>

        <div className="mt-4">
          <SectionLabel>Operations</SectionLabel>
          <div className="space-y-0.5">
            {visibleOps.map((item) => (
              <NavRow key={item.to} {...item} />
            ))}
          </div>
        </div>
      </nav>

      {/* Footer: settings + feedback */}
      <div className="border-t border-black/[0.05] px-2 py-2">
        <button
          type="button"
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium text-content-secondary transition-colors hover:bg-black/[0.04] hover:text-content-primary"
        >
          <Settings size={16} />
          <span>Settings</span>
        </button>
        <button
          type="button"
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium text-content-secondary transition-colors hover:bg-black/[0.04] hover:text-content-primary"
        >
          <MessageCircle size={16} />
          <span>Feedback?</span>
        </button>
      </div>
    </aside>
  )
}
