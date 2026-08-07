import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { SekondBrainRail } from './SekondBrainRail'
import { Header } from './Header'
import { AnimatedBackground } from './AnimatedBackground'

/**
 * Root app shell.
 *
 * Responsive layout (S9N-6167):
 *   ≥1024px (lg): [56px rail][240px sidebar][main]           — full
 *   768–1023px (md): [56px rail][64px icon sidebar][main]    — icon rail
 *   <768px: rail + sidebar hidden off-canvas; hamburger in the
 *           header opens the sidebar as a drawer over a backdrop; main
 *           uses the full width.
 *
 * The animated gradient background is rendered behind the inner sidebar
 * and main column (the outer rail is opaque dark and sits on top).
 */
export function AppShell() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const location = useLocation()

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setMobileNavOpen(false)
  }, [location.pathname])

  return (
    <div className="relative min-h-screen">
      <AnimatedBackground />

      <SekondBrainRail />
      <Sidebar mobileOpen={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />

      {/* Mobile drawer backdrop */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          aria-hidden
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      <div className="relative z-10 ml-0 md:ml-[120px] lg:ml-[296px]">
        <Header onMenuClick={() => setMobileNavOpen(true)} />
        <main className="px-4 py-6 sm:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
