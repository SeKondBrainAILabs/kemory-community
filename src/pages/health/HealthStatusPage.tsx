import { useState, useEffect, useRef } from 'react'
import { PageShell } from '@/components/layout/PageShell'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { CardSkeleton } from '@/components/shared/LoadingSkeleton'
import { useDeepHealth } from '@/hooks/useHealth'
import { formatLatency } from '@/lib/utils'
import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts'
import type { ServiceCheck } from '@/api/types'

interface LatencyPoint {
  time: number
  value: number
}

export function HealthStatusPage() {
  const { data, isLoading } = useDeepHealth()
  const historyRef = useRef<Record<string, LatencyPoint[]>>({})

  useEffect(() => {
    if (!data) return
    const now = Date.now()
    for (const [name, check] of Object.entries(data.checks)) {
      if (!historyRef.current[name]) historyRef.current[name] = []
      historyRef.current[name].push({
        time: now,
        value: check.latency_ms ?? 0,
      })
      // Keep last 60 points (30 min at 30s interval)
      if (historyRef.current[name].length > 60) {
        historyRef.current[name] = historyRef.current[name].slice(-60)
      }
    }
  }, [data])

  return (
    <PageShell>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="text-sm text-content-secondary">
            Auto-refreshing every 30 seconds
          </p>
        </div>
        {data && <StatusBadge status={data.status} />}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {isLoading
          ? Array.from({ length: 4 }).map((_, i) => <CardSkeleton key={i} />)
          : data &&
            Object.entries(data.checks).map(([name, check]) => (
              <ServiceCard
                key={name}
                name={name}
                check={check}
                history={historyRef.current[name] ?? []}
              />
            ))}
      </div>

      {data && (
        <div className="mt-6 rounded-lg border border-border bg-white p-4 text-xs text-content-tertiary">
          <span>Service: {data.service}</span>
          <span className="mx-2">&middot;</span>
          <span>Version: {data.version}</span>
          <span className="mx-2">&middot;</span>
          <span>Environment: {data.environment}</span>
        </div>
      )}
    </PageShell>
  )
}

function ServiceCard({
  name,
  check,
  history,
}: {
  name: string
  check: ServiceCheck
  history: LatencyPoint[]
}) {
  const [, setTick] = useState(0)
  // Force re-render when health data updates to show sparkline
  useEffect(() => {
    setTick((t) => t + 1)
  }, [history.length])

  return (
    <div className="rounded-lg border border-border bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-base font-semibold capitalize text-content-primary">{name}</span>
        <StatusBadge status={check.status} />
      </div>

      {check.latency_ms != null && (
        <div className="mt-2 text-2xl font-semibold text-content-primary">
          {formatLatency(check.latency_ms)}
        </div>
      )}

      {check.error && (
        <div className="mt-2 rounded bg-red-50 px-3 py-2 text-xs text-status-danger">
          {check.error}
        </div>
      )}

      {history.length > 1 && (
        <div className="mt-3 h-12">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <YAxis hide domain={['auto', 'auto']} />
              <Line
                type="monotone"
                dataKey="value"
                stroke={check.status === 'healthy' ? '#16a34a' : '#dc2626'}
                strokeWidth={1.5}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
