import { useState } from 'react'
import { PageShell } from '@/components/layout/PageShell'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { useWaitlistEntries, useWaitlistStats, useWaitlistAction } from '@/hooks/useWaitlist'
import { cn } from '@/lib/utils'
import { Check, X, Users, TrendingUp, UserCheck, Award, type LucideIcon } from 'lucide-react'

const statusFilters = ['all', 'pending', 'approved', 'rejected'] as const

export function WaitlistManagementPage() {
  const [filter, setFilter] = useState<string>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const entries = useWaitlistEntries({
    status: filter === 'all' ? undefined : filter,
    limit: 100,
  })
  const stats = useWaitlistStats()
  const { approveMutation, rejectMutation, bulkApproveMutation } = useWaitlistAction()

  const toggleSelect = (userId: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(userId) ? next.delete(userId) : next.add(userId)
      return next
    })
  }

  const handleBulkApprove = () => {
    if (selected.size === 0) return
    bulkApproveMutation.mutate({ userIds: [...selected] })
    setSelected(new Set())
  }

  return (
    <PageShell>
      {/* Stats cards */}
      {stats.data && (
        <div className="mb-6 grid grid-cols-4 gap-4">
          <StatCard icon={Users} label="Total" value={stats.data.total} />
          <StatCard icon={TrendingUp} label="Pending" value={stats.data.pending} color="amber" />
          <StatCard icon={UserCheck} label="Approved" value={stats.data.approved} color="emerald" />
          <StatCard icon={Award} label="Referrals" value={stats.data.total_referrals} color="indigo" />
        </div>
      )}

      {/* Filter pills + bulk action */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex gap-2">
          {statusFilters.map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={cn(
                'rounded-full px-4 py-1.5 text-xs font-medium capitalize transition-colors',
                filter === s
                  ? 'bg-brand-primary text-white'
                  : 'border border-border bg-white text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {s}
            </button>
          ))}
        </div>
        {selected.size > 0 && (
          <button
            onClick={handleBulkApprove}
            disabled={bulkApproveMutation.isPending}
            className="rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            Approve {selected.size} selected
          </button>
        )}
      </div>

      {/* Table */}
      {entries.isLoading ? (
        <LoadingSkeleton lines={8} />
      ) : entries.isError ? (
        /* Fix KMV-QA-010: Show helpful error instead of blank page on 403/500/503 */
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm font-semibold text-red-600">Unable to load waitlist entries</p>
          <p className="mt-1 text-xs text-content-tertiary">
            {(() => {
              const status = (entries.error as { status?: number })?.status
              if (status === 503)
                return 'The waitlist service is temporarily unavailable — a database migration may be pending. Please try again shortly.'
              if (status === 403)
                return 'Access denied. Ensure your account has the admin role assigned.'
              return 'An unexpected error occurred loading the waitlist. Check the backend logs for details.'
            })()}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-surface-secondary text-left text-xs font-medium uppercase text-content-tertiary">
                <th className="px-4 py-3 w-10">
                  <input
                    type="checkbox"
                    onChange={(e) => {
                      if (e.target.checked) {
                        const pending = entries.data?.entries
                          .filter((e) => e.status === 'pending')
                          .map((e) => e.user_id) ?? []
                        setSelected(new Set(pending))
                      } else {
                        setSelected(new Set())
                      }
                    }}
                    className="rounded"
                  />
                </th>
                <th className="px-4 py-3">#</th>
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Service</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Referrals</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Joined</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {entries.data?.entries.map((entry) => (
                <tr key={entry.id} className="border-b border-border last:border-0 hover:bg-surface-secondary/50">
                  <td className="px-4 py-3">
                    {entry.status === 'pending' && (
                      <input
                        type="checkbox"
                        checked={selected.has(entry.user_id)}
                        onChange={() => toggleSelect(entry.user_id)}
                        className="rounded"
                      />
                    )}
                  </td>
                  <td className="px-4 py-3 text-content-tertiary">{entry.position}</td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-content-primary">
                      {entry.display_name || entry.email}
                    </div>
                    {entry.display_name && (
                      <div className="text-xs text-content-tertiary">{entry.email}</div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded bg-surface-secondary px-2 py-0.5 text-xs">
                      {entry.service}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={entry.status} />
                  </td>
                  <td className="px-4 py-3">
                    <span className="font-medium">{entry.referral_count}</span>
                    {entry.referred_by_code && (
                      <span className="ml-1 text-xs text-content-tertiary">
                        (via {entry.referred_by_code})
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-content-tertiary">{entry.source}</td>
                  <td className="px-4 py-3 text-content-tertiary">
                    {entry.joined_at
                      ? new Date(entry.joined_at).toLocaleDateString()
                      : '—'}
                  </td>
                  <td className="px-4 py-3">
                    {entry.status === 'pending' && (
                      <div className="flex gap-1">
                        <button
                          onClick={() =>
                            approveMutation.mutate({ userId: entry.user_id })
                          }
                          disabled={approveMutation.isPending}
                          className="rounded p-1 text-emerald-600 hover:bg-emerald-50"
                          title="Approve"
                        >
                          <Check size={16} />
                        </button>
                        <button
                          onClick={() =>
                            rejectMutation.mutate({ userId: entry.user_id })
                          }
                          disabled={rejectMutation.isPending}
                          className="rounded p-1 text-red-500 hover:bg-red-50"
                          title="Reject"
                        >
                          <X size={16} />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {entries.data?.entries.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-content-tertiary">
                    No waitlist entries found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Top referrers */}
      {stats.data?.top_referrers && stats.data.top_referrers.length > 0 && (
        <div className="mt-6 rounded-lg border border-border bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold text-content-primary">Top Referrers</h3>
          <div className="space-y-2">
            {stats.data.top_referrers.map((r, i) => (
              <div key={i} className="flex items-center justify-between text-sm">
                <span className="text-content-secondary">{r.name}</span>
                <span className="font-medium text-brand-primary">{r.count} referrals</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </PageShell>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
  color = 'default',
}: {
  icon: LucideIcon
  label: string
  value: number
  color?: 'default' | 'amber' | 'emerald' | 'indigo'
}) {
  const colors = {
    default: 'bg-surface-secondary text-content-secondary',
    amber: 'bg-amber-50 text-amber-600',
    emerald: 'bg-emerald-50 text-emerald-600',
    indigo: 'bg-indigo-50 text-indigo-600',
  }

  return (
    <div className="rounded-lg border border-border bg-white p-4">
      <div className="flex items-center gap-2">
        <div className={cn('rounded-lg p-2', colors[color])}>
          <Icon size={16} />
        </div>
        <span className="text-xs font-medium text-content-tertiary">{label}</span>
      </div>
      <div className="mt-2 text-2xl font-semibold text-content-primary">{value}</div>
    </div>
  )
}
