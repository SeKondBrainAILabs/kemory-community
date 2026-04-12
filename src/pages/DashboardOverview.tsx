import { PageShell } from '@/components/layout/PageShell'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { CardSkeleton } from '@/components/shared/LoadingSkeleton'
import { useDeepHealth } from '@/hooks/useHealth'
import { useAgents } from '@/hooks/useAgents'
import { useNamespaces } from '@/hooks/useMemories'
import { useAuditLogs } from '@/hooks/useAudit'
import { formatRelativeTime, formatLatency } from '@/lib/utils'
import { Link } from 'react-router-dom'
import {
  Bot,
  Database,
  Heart,
  ScrollText,
  ArrowRight,
  AlertTriangle,
} from 'lucide-react'

export function DashboardOverview() {
  const health = useDeepHealth()
  const agents = useAgents()
  const namespaces = useNamespaces()
  const recentAudit = useAuditLogs({ limit: 5 })

  const totalMemories = namespaces.data?.reduce((sum, ns) => sum + ns.count, 0) ?? 0
  const activeAgents = agents.data?.filter((a) => a.status === 'active').length ?? 0

  return (
    <PageShell>
      {/* Stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {agents.isLoading ? (
          <CardSkeleton />
        ) : agents.isError ? (
          <ErrorCard icon={Bot} label="Agents" to="/agents" />
        ) : (
          <StatCard
            icon={Bot}
            label="Agents"
            value={agents.data?.length ?? 0}
            sub={`${activeAgents} active`}
            to="/agents"
          />
        )}
        {namespaces.isLoading ? (
          <CardSkeleton />
        ) : namespaces.isError ? (
          <ErrorCard icon={Database} label="Memories" to="/memories" />
        ) : (
          <StatCard
            icon={Database}
            label="Memories"
            value={totalMemories}
            sub={`${namespaces.data?.length ?? 0} namespaces`}
            to="/memories"
          />
        )}
        {health.isLoading ? (
          <CardSkeleton />
        ) : health.isError ? (
          <ErrorCard icon={Heart} label="System" to="/health" />
        ) : (
          <StatCard
            icon={Heart}
            label="System"
            value={health.data?.status === 'healthy' ? 'Healthy' : 'Degraded'}
            sub={`${Object.keys(health.data?.checks ?? {}).length} services`}
            to="/health"
          />
        )}
        {recentAudit.isLoading ? (
          <CardSkeleton />
        ) : recentAudit.isError ? (
          <ErrorCard icon={ScrollText} label="Audit" to="/audit" />
        ) : (
          <StatCard
            icon={ScrollText}
            label="Audit"
            value={recentAudit.data?.total ?? 0}
            sub="total events"
            to="/audit"
          />
        )}
      </div>

      {/* Service health */}
      <div className="mt-6">
        <h2 className="mb-3 text-sm font-semibold text-content-primary">Service Health</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {health.data
            ? Object.entries(health.data.checks).map(([name, check]) => (
                <div
                  key={name}
                  className="rounded-lg border border-border bg-white p-4 shadow-sm"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium capitalize text-content-primary">
                      {name}
                    </span>
                    <StatusBadge status={check.status} />
                  </div>
                  {check.latency_ms != null && (
                    <div className="mt-2 text-xs text-content-tertiary">
                      {formatLatency(check.latency_ms)}
                    </div>
                  )}
                </div>
              ))
            : health.isError
              ? ['postgres', 'redis', 'falkordb', 'weaviate'].map((name) => (
                  <div
                    key={name}
                    className="rounded-lg border border-status-warning/30 bg-status-warning/5 p-4"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium capitalize text-content-primary">
                        {name}
                      </span>
                      <StatusBadge status="unknown" />
                    </div>
                    <div className="mt-2 text-xs text-content-tertiary">No data</div>
                  </div>
                ))
              : Array.from({ length: 4 }).map((_, i) => (
                  <div
                    key={i}
                    className="skeleton h-20 rounded-lg"
                  />
                ))}
        </div>
      </div>

      {/* Recent activity */}
      <div className="mt-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-content-primary">Recent Activity</h2>
          <Link
            to="/audit"
            className="flex items-center gap-1 text-xs font-medium text-brand-primary hover:underline"
          >
            View all <ArrowRight size={12} />
          </Link>
        </div>
        <div className="space-y-2">
          {recentAudit.data?.items.map((entry) => (
            <div
              key={entry.audit_id}
              className="flex items-center justify-between rounded-lg border border-border bg-white px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <StatusBadge status={entry.outcome} />
                <span className="text-sm text-content-primary">{entry.action}</span>
                {entry.agent_id && (
                  <span className="text-xs text-content-tertiary">
                    by {entry.agent_id.slice(0, 8)}...
                  </span>
                )}
              </div>
              <span className="text-xs text-content-tertiary">
                {formatRelativeTime(entry.created_at)}
              </span>
            </div>
          ))}
          {recentAudit.data?.items.length === 0 && (
            <div className="rounded-lg border border-border bg-white px-4 py-8 text-center text-sm text-content-tertiary">
              No audit events yet
            </div>
          )}
        </div>
      </div>
    </PageShell>
  )
}

function ErrorCard({
  icon: Icon,
  label,
  to,
}: {
  icon: typeof Bot
  label: string
  to: string
}) {
  return (
    <Link
      to={to}
      className="group rounded-lg border border-status-warning/30 bg-status-warning/5 p-5 shadow-sm transition-shadow hover:shadow-md"
    >
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-status-warning/10 text-status-warning">
          <Icon size={20} />
        </div>
        <div>
          <div className="text-xs font-medium text-content-secondary">{label}</div>
          <div className="flex items-center gap-1.5 text-sm font-medium text-status-warning">
            <AlertTriangle size={14} />
            Unavailable
          </div>
        </div>
      </div>
      <div className="mt-2 text-xs text-content-tertiary">API not reachable</div>
    </Link>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  to,
}: {
  icon: typeof Bot
  label: string
  value: string | number
  sub: string
  to: string
}) {
  return (
    <Link
      to={to}
      className="group rounded-lg border border-border bg-white p-5 shadow-sm transition-shadow hover:shadow-md"
    >
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-primary/10 text-brand-primary">
          <Icon size={20} />
        </div>
        <div>
          <div className="text-xs font-medium text-content-secondary">{label}</div>
          <div className="text-xl font-semibold text-content-primary">{value}</div>
        </div>
      </div>
      <div className="mt-2 text-xs text-content-tertiary">{sub}</div>
    </Link>
  )
}
