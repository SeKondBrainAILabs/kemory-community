import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Header } from './Header'

export function AppShell() {
  return (
    <div className="min-h-screen bg-surface-secondary">
      <Sidebar />
      <div className="ml-[280px] transition-all duration-200">
        <Header />
        <main className="p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
