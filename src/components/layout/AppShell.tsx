import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { SekondBrainRail } from './SekondBrainRail'
import { Header } from './Header'
import { AnimatedBackground } from './AnimatedBackground'

/**
 * Root app shell.
 *
 * Layout (left -> right):
 *   [ 56px  SekondBrain app-switcher rail ]
 *   [ 240px Memory Vault inner sidebar    ]
 *   [ remainder: header + main            ]
 *
 * The animated gradient background is rendered behind the inner sidebar
 * and main column (the outer rail is opaque dark and sits on top).
 */
export function AppShell() {
  return (
    <div className="relative min-h-screen">
      <AnimatedBackground />

      <SekondBrainRail />
      <Sidebar />

      <div className="relative z-10 ml-[296px]">
        <Header />
        <main className="px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
