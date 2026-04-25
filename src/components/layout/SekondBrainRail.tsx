import { Brain, Sparkles, FileText, User, LogOut } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { cn } from '@/lib/utils'

/**
 * Outer SekondBrain app-switcher rail.
 *
 * This is the OUTERMOST rail — it switches between top-level SekondBrain
 * apps (Memory, Pulse, Kanvas, Kit, ...). The inner rail (Sidebar.tsx)
 * is the *active* app's own nav.
 *
 * - ~56px wide, dark opaque surface (contrast against the animated
 *   gradient in the main area and the light inner Memory Sidebar).
 * - SekondBrain Kora logo at top.
 * - Memory is the active top-level app here (Memory Vault is this app),
 *   shown with a filled indicator pill.
 * - Other SekondBrain apps (Pulse, Kanvas) render as dimmed anchor
 *   points — they'll become real links when those apps ship.
 * - Profile button at bottom (sign in / sign out).
 */

type BrainApp = {
  id: string
  label: string
  icon: typeof Brain
  active?: boolean
  disabled?: boolean
}

const apps: BrainApp[] = [
  { id: 'memory', label: 'Memory', icon: Brain, active: true },
  { id: 'pulse', label: 'Pulse', icon: Sparkles, disabled: true },
  { id: 'kanvas', label: 'Kanvas', icon: FileText, disabled: true },
]

function AppTile({ app }: { app: BrainApp }) {
  const Icon = app.icon
  return (
    <button
      type="button"
      disabled={app.disabled}
      aria-label={app.label}
      aria-current={app.active ? 'true' : undefined}
      title={app.label}
      className={cn(
        'group relative flex h-10 w-10 items-center justify-center rounded-[10px] transition-colors',
        app.active
          ? 'bg-white/10 text-white shadow-inner ring-1 ring-white/15'
          : 'text-white/45 hover:text-white hover:bg-white/5',
        app.disabled && 'cursor-not-allowed opacity-50 hover:bg-transparent hover:text-white/45',
      )}
    >
      {/* Active pill indicator on the left edge */}
      {app.active && (
        <span
          aria-hidden
          className="absolute left-[-14px] top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-white"
        />
      )}
      <Icon size={18} />
      {/* Tooltip */}
      <span
        className="pointer-events-none absolute left-[52px] top-1/2 z-50 -translate-y-1/2 whitespace-nowrap rounded-md bg-black/85 px-2 py-1 text-xs font-medium text-white opacity-0 shadow-lg backdrop-blur-sm transition-opacity duration-150 group-hover:opacity-100"
        role="tooltip"
      >
        {app.label}
      </span>
    </button>
  )
}

export function SekondBrainRail() {
  const { isAuthenticated, user, login, logout } = useAuth()
  const initials = user
    ? `${user.firstName?.[0] ?? ''}${user.lastName?.[0] ?? ''}`.toUpperCase() ||
      user.email?.[0]?.toUpperCase() ||
      'U'
    : null

  return (
    <aside
      aria-label="SekondBrain apps"
      className="fixed left-0 top-0 z-50 flex h-screen w-[56px] flex-col items-center justify-between bg-[#0b0b10] px-[8px] py-[14px]"
    >
      {/* Brand mark + vertical wordmark */}
      <div className="flex flex-col items-center gap-[22px]">
        <div
          className="flex h-10 w-10 items-center justify-center"
          aria-label="SekondBrain"
          title="SekondBrain"
        >
          <img
            src="/sekondbrain-logo-color.png"
            alt="SekondBrain"
            width={30}
            height={30}
            className="block h-[30px] w-[30px]"
          />
        </div>

        <div className="h-px w-7 rounded-full bg-white/10" />

        {/* App tiles */}
        <nav className="flex flex-col items-center gap-[6px]">
          {apps.map((a) => (
            <AppTile key={a.id} app={a} />
          ))}
        </nav>
      </div>

      {/* Profile / auth */}
      {isAuthenticated && user ? (
        <button
          type="button"
          onClick={logout}
          aria-label={`Sign out ${user.firstName ?? user.email}`}
          title={`Sign out ${user.firstName ?? user.email}`}
          className="group relative flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-[11px] font-semibold text-white transition-colors hover:bg-white/20"
        >
          <span aria-hidden>{initials}</span>
          <LogOut
            size={11}
            className="absolute -right-0.5 -top-0.5 rounded-full bg-[#0b0b10] p-0.5 text-white/70"
          />
          <span
            className="pointer-events-none absolute left-[52px] top-1/2 -translate-y-1/2 whitespace-nowrap rounded-md bg-black/85 px-2 py-1 text-xs font-medium text-white opacity-0 shadow-lg backdrop-blur-sm transition-opacity duration-150 group-hover:opacity-100"
            role="tooltip"
          >
            Sign out
          </span>
        </button>
      ) : (
        <button
          type="button"
          onClick={login}
          aria-label="Sign in"
          title="Sign in"
          className="group relative flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-white/70 transition-colors hover:bg-white/20 hover:text-white"
        >
          <User size={16} />
          <span
            className="pointer-events-none absolute left-[52px] top-1/2 -translate-y-1/2 rounded-md bg-black/85 px-2 py-1 text-xs font-medium text-white opacity-0 shadow-lg backdrop-blur-sm transition-opacity duration-150 group-hover:opacity-100"
            role="tooltip"
          >
            Sign in
          </span>
        </button>
      )}
    </aside>
  )
}
