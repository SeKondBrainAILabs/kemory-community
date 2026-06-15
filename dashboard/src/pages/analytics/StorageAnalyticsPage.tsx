/**
 * UX fix: Pie chart previously rendered all 500+ namespaces as labels,
 * making it completely unreadable. Now caps at top 15 by memory count
 * and groups the remainder as "Other" using a horizontal bar chart.
 */
import { useMemo } from 'react'
import { PageShell } from '@/components/layout/PageShell'
import { CardSkeleton } from '@/components/shared/LoadingSkeleton'
import { useNamespaces } from '@/hooks/useMemories'
import { useAgents } from '@/hooks/useAgents'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { Database, Bot, FolderOpen } from 'lucide-react'

const COLORS = [
  '#6366f1', '#8b5cf6', '#3b82f6', '#16a34a', '#d97706',
  '#dc2626', '#0891b2', '#7c3aed', '#2563eb', '#059669',
  '#f59e0b', '#ef4444', '#10b981', '#6d28d9', '#1d4ed8',
]

const TOP_N = 15

export function StorageAnalyticsPage() {
  const namespaces = useNamespaces()
  const agents = useAgents()

  const totalMemories = namespaces.data?.reduce((sum, ns) => sum + ns.count, 0) ?? 0

  // Cap to top N namespaces by count; group the rest as "Other"
  const chartData = useMemo(() => {
    if (!namespaces.data || namespaces.data.length === 0) return []
    const sorted = [...namespaces.data].sort((a, b) => b.count - a.count)
    if (sorted.length <= TOP_N) {
      return sorted.map((ns) => ({ name: ns.namespace, value: ns.count }))
    }
    const top = sorted.slice(0, TOP_N)
    const otherCount = sorted.slice(TOP_N).reduce((sum, ns) => sum + ns.count, 0)
    return [
      ...top.map((ns) => ({ name: ns.namespace, value: ns.count })),
      { name: `Other (${sorted.length - TOP_N} namespaces)`, value: otherCount },
    ]
  }, [namespaces.data])

  return (
    <PageShell>
      {/* Summary cards */}
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        {namespaces.isLoading || agents.isLoading ? (
          <>
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </>
        ) : (
          <>
            <SummaryCard
              icon={Database}
              label="Total Memories"
              value={totalMemories}
            />
            <SummaryCard
              icon={FolderOpen}
              label="Namespaces"
              value={namespaces.data?.length ?? 0}
            />
            <SummaryCard
              icon={Bot}
              label="Agents"
              value={agents.data?.length ?? 0}
            />
          </>
        )}
      </div>

      {/* Top-N namespace distribution bar chart */}
      <div className="rounded-lg border border-border bg-white p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-content-primary">
            Top {TOP_N} Namespaces by Memory Count
          </h2>
          {namespaces.data && namespaces.data.length > TOP_N && (
            <span className="text-xs text-content-tertiary">
              Showing top {TOP_N} of {namespaces.data.length} namespaces
            </span>
          )}
        </div>
        {chartData.length > 0 ? (
          <div className="h-96">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{ top: 0, right: 24, left: 8, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={180}
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v: string) =>
                    v.length > 24 ? `${v.slice(0, 22)}\u2026` : v
                  }
                />
                <Tooltip
                  formatter={(value: number) => [value.toLocaleString(), 'Memories']}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {chartData.map((_, i) => (
                    <Cell
                      key={i}
                      fill={i === TOP_N ? '#94a3b8' : COLORS[i % COLORS.length]}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="py-8 text-center text-sm text-content-tertiary">
            No namespace data
          </div>
        )}
      </div>

      {/* Agent activity table */}
      {agents.data && agents.data.length > 0 && (
        <div className="mt-6 rounded-lg border border-border bg-white p-6">
          <h2 className="mb-4 text-sm font-semibold text-content-primary">Agent Activity</h2>
          <div className="space-y-3">
            {agents.data.map((agent) => (
              <div
                key={agent.agent_id}
                className="flex items-center justify-between rounded-lg bg-surface-secondary px-4 py-3"
              >
                <div>
                  <div className="text-sm font-medium text-content-primary">{agent.agent_name}</div>
                  <div className="text-xs text-content-tertiary">{agent.status}</div>
                </div>
                <div className="flex gap-6 text-center">
                  <div>
                    <div className="text-lg font-semibold text-content-primary">{agent.total_reads}</div>
                    <div className="text-xs text-content-tertiary">reads</div>
                  </div>
                  <div>
                    <div className="text-lg font-semibold text-content-primary">{agent.total_writes}</div>
                    <div className="text-xs text-content-tertiary">writes</div>
                  </div>
                  <div>
                    <div className="text-lg font-semibold text-status-danger">{agent.denied_requests}</div>
                    <div className="text-xs text-content-tertiary">denied</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </PageShell>
  )
}

function SummaryCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Database
  label: string
  value: number
}) {
  return (
    <div className="rounded-lg border border-border bg-white p-5 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-primary/10 text-brand-primary">
          <Icon size={20} />
        </div>
        <div>
          <div className="text-xs font-medium text-content-secondary">{label}</div>
          <div className="text-2xl font-semibold text-content-primary">{value}</div>
        </div>
      </div>
    </div>
  )
}
