import { PageShell } from '@/components/layout/PageShell'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { CardSkeleton } from '@/components/shared/LoadingSkeleton'
import { useDeepHealth } from '@/hooks/useHealth'
import { useNamespaces } from '@/hooks/useMemories'
import { formatLatency } from '@/lib/utils'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  Database,
  FolderTree,
  Heart,
  AlertTriangle,
  Settings2,
} from 'lucide-react'

export function DashboardOverview() {
  const health = useDeepHealth()
  const namespaces = useNamespaces()

  const totalMemories = namespaces.data?.reduce((sum, ns) => sum + ns.count, 0) ?? 0

  return (
    <PageShell>
      {/* Stat cards */}
      <div className="grid gap-4 sm:grid-cols-3">
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
        {namespaces.isLoading ? (
          <CardSkeleton />
        ) : namespaces.isError ? (
          <ErrorCard icon={FolderTree} label="Namespaces" to="/namespaces" />
        ) : (
          <StatCard
            icon={FolderTree}
            label="Namespaces"
            value={namespaces.data?.length ?? 0}
            sub="local memory groups"
            to="/namespaces"
          />
        )}
        {health.isLoading ? (
          <CardSkeleton />
        ) : health.isError ? (
          <ErrorCard icon={Heart} label="System" to="/doctor" />
        ) : (
          <StatCard
            icon={Heart}
            label="System"
            value={health.data?.status === 'healthy' ? 'Healthy' : 'Degraded'}
            sub={`${Object.keys(health.data?.checks ?? {}).length} services`}
            to="/doctor"
          />
        )}
      </div>

      {!namespaces.isLoading && !namespaces.isError && totalMemories === 0 && (
        <div className="mt-6 flex flex-col gap-4 border-y border-border py-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-brand-primary/10 text-brand-primary">
              <Settings2 size={18} />
            </div>
            <div>
              <div className="text-sm font-semibold text-content-primary">Complete local setup</div>
              <div className="mt-1 text-sm text-content-secondary">Review access, embeddings, optional providers, and backup.</div>
            </div>
          </div>
          <Link to="/settings" className="inline-flex items-center gap-2 self-start rounded-md bg-brand-primary px-4 py-2 text-sm font-medium text-white sm:self-auto">
            Community admin <ArrowRight size={16} />
          </Link>
        </div>
      )}

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
              ? ['postgres', 'redis'].map((name) => (
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
              : Array.from({ length: 2 }).map((_, i) => (
                  <div
                    key={i}
                    className="skeleton h-20 rounded-lg"
                  />
                ))}
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
  icon: typeof Database
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
  icon: typeof Database
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
