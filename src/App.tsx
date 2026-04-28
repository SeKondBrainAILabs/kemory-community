import { Routes, Route, Navigate } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { RequireAuth } from '@/components/auth/RequireAuth'
import { LoginPage } from '@/pages/LoginPage'
import { UnauthorizedPage } from '@/pages/UnauthorizedPage'
import { DashboardOverview } from '@/pages/DashboardOverview'
import { AgentListPage } from '@/pages/agents/AgentListPage'
import { AgentDetailPage } from '@/pages/agents/AgentDetailPage'
import { HealthStatusPage } from '@/pages/health/HealthStatusPage'
import { AuditLogPage } from '@/pages/audit/AuditLogPage'
import { PermissionListPage } from '@/pages/permissions/PermissionListPage'
import { MemoryExplorerPage } from '@/pages/memories/MemoryExplorerPage'
import { NamespacesPage } from '@/pages/namespaces/NamespacesPage'
import { AccessMapPage } from '@/pages/access/AccessMapPage'
import { AccessGraphPage } from '@/pages/access/AccessGraphPage'  // F12
import { ConsentQueuePage } from '@/pages/consent/ConsentQueuePage'
import { StorageAnalyticsPage } from '@/pages/analytics/StorageAnalyticsPage'
import { SecurityAlertsPage } from '@/pages/security/SecurityAlertsPage'
import { ConnectorsPage } from '@/pages/connectors/ConnectorsPage'

export function App() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/unauthorized" element={<UnauthorizedPage />} />

      {/* Protected routes */}
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardOverview />} />
        <Route path="agents" element={<AgentListPage />} />
        <Route path="agents/:agentId" element={<AgentDetailPage />} />
        <Route path="system-health" element={<HealthStatusPage />} />
        <Route path="audit" element={<AuditLogPage />} />
        <Route path="permissions" element={<PermissionListPage />} />
        <Route path="memories" element={<MemoryExplorerPage />} />
        <Route path="namespaces" element={<NamespacesPage />} />
        <Route path="access" element={<AccessMapPage />} />
        <Route path="access-graph" element={<AccessGraphPage />} />  {/* F12 */}
        <Route path="consent" element={<ConsentQueuePage />} />
        <Route path="analytics" element={<StorageAnalyticsPage />} />
        <Route path="connectors" element={<ConnectorsPage />} />

        {/* Super admin only */}
        <Route
          path="security"
          element={
            <RequireAuth requiredRole="super_admin">
              <SecurityAlertsPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
