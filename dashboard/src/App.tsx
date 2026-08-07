import { Routes, Route, Navigate } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { DashboardOverview } from '@/pages/DashboardOverview'
import { HealthStatusPage } from '@/pages/health/HealthStatusPage'
import { MemoryExplorerPage } from '@/pages/memories/MemoryExplorerPage'
import { NamespacesPage } from '@/pages/namespaces/NamespacesPage'
import { ChatsListPage } from '@/pages/chats/ChatsListPage'
import { ChatDetailPage } from '@/pages/chats/ChatDetailPage'
import { ChatMappingsPage } from '@/pages/chat-mappings/ChatMappingsPage'
import { SettingsPage } from '@/pages/settings/SettingsPage'
import { ArtifactsPage } from '@/pages/artifacts/ArtifactsPage'

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardOverview />} />
        <Route path="doctor" element={<HealthStatusPage />} />
        <Route path="system-health" element={<Navigate to="/doctor" replace />} />
        <Route path="memories" element={<MemoryExplorerPage />} />
        <Route path="namespaces" element={<NamespacesPage />} />
        <Route path="chats" element={<ChatsListPage />} />
        <Route path="chats/:chatId" element={<ChatDetailPage />} />
        <Route path="chat-mappings" element={<ChatMappingsPage />} />
        <Route path="artifacts" element={<ArtifactsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
