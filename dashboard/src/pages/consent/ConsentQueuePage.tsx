/**
 * Memory Vault — Consent Queue Page
 *
 * Fix KMV-QA-006: The page previously filtered audit logs for entries
 * containing a consent_id in their details field.  Since the admin's
 * Keycloak UUID does not match the user_id stored in audit records the
 * audit log was always empty, so the consent queue always appeared blank.
 *
 * The page now fetches consent requests directly from the ConsentRequest
 * table via GET /api/v1/gatekeeper/consent (useConsentRequests hook),
 * which returns real data regardless of the admin user_id mismatch.
 */
import { useState } from 'react'
import { PageShell } from '@/components/layout/PageShell'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { useConsentRequests, useResolveConsent } from '@/hooks/usePermissions'
import { useAgents } from '@/hooks/useAgents'
import { formatRelativeTime } from '@/lib/utils'
import { Check, X, Clock, RefreshCw } from 'lucide-react'

type StatusFilter = 'pending' | 'approved' | 'denied' | 'timeout' | undefined

export function ConsentQueuePage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('pending')
  const { data, isLoading, refetch, isFetching } = useConsentRequests(statusFilter)
  const agents = useAgents()
  const resolve = useResolveConsent()

  const getAgentName = (agentId: string) => {
    return agents.data?.find((a) => a.agent_id === agentId)?.agent_name ?? agentId.slice(0, 8) + '…'
  }

  const isExpired = (expiresAt: string) => new Date(expiresAt) < new Date()

  const filterTabs: { label: string; value: StatusFilter }[] = [
    { label: 'Pending', value: 'pending' },
    { label: 'Approved', value: 'approved' },
    { label: 'Denied', value: 'denied' },
    { label: 'Timed Out', value: 'timeout' },
    { label: 'All', value: undefined },
  ]

  return (
    <PageShell>
      <p className="mb-4 text-sm text-content-secondary">
        Just-in-time consent requests from agents. Approve or deny pending access requests.
        Auto-refreshes every 5 seconds.
      </p>

      {/* Filter tabs + refresh */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex gap-1">
          {filterTabs.map((tab) => (
            <button
              key={tab.label}
              onClick={() => setStatusFilter(tab.value)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                statusFilter === tab.value
                  ? 'bg-brand-primary text-white'
                  : 'border border-border text-content-secondary hover:bg-surface-secondary'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-1.5 text-xs text-content-tertiary hover:text-content-secondary disabled:opacity-50"
        >
          <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {isLoading ? (
        <LoadingSkeleton lines={4} />
      ) : (data ?? []).length > 0 ? (
        <div className="space-y-3">
          {(data ?? []).map((consent) => (
            <div
              key={consent.consent_id}
              className="flex items-start justify-between rounded-lg border border-border bg-white px-5 py-4 shadow-sm"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <StatusBadge status={consent.status} />
                  <span className="text-sm font-medium text-content-primary">
                    {getAgentName(consent.agent_id)}
                  </span>
                  <span className="text-sm text-content-secondary">
                    requests{' '}
                    <code className="rounded bg-surface-tertiary px-1 text-xs">
                      {consent.requested_scope}
                    </code>
                  </span>
                </div>

                {consent.requested_resource && (
                  <div className="mt-1 text-xs text-content-tertiary">
                    Resource: {consent.requested_resource}
                  </div>
                )}

                <div className="mt-1 flex items-center gap-3 text-xs text-content-tertiary">
                  <span>{formatRelativeTime(consent.created_at)}</span>
                  {consent.status === 'pending' && (
                    <span className={`flex items-center gap-1 ${isExpired(consent.expires_at) ? 'text-status-danger' : ''}`}>
                      <Clock size={10} />
                      {isExpired(consent.expires_at) ? 'Expired' : `Expires ${formatRelativeTime(consent.expires_at)}`}
                    </span>
                  )}
                  {consent.resolved_at && (
                    <span>Resolved {formatRelativeTime(consent.resolved_at)}</span>
                  )}
                </div>
              </div>

              {consent.status === 'pending' && !isExpired(consent.expires_at) && (
                <div className="ml-4 flex gap-2 shrink-0">
                  <button
                    onClick={() => resolve.mutate({ consentId: consent.consent_id, approved: true })}
                    disabled={resolve.isPending}
                    className="flex items-center gap-1 rounded-lg bg-status-success px-3 py-2 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                  >
                    <Check size={14} /> Approve
                  </button>
                  <button
                    onClick={() => resolve.mutate({ consentId: consent.consent_id, approved: false })}
                    disabled={resolve.isPending}
                    className="flex items-center gap-1 rounded-lg bg-status-danger px-3 py-2 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                  >
                    <X size={14} /> Deny
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-white p-8 text-center text-sm text-content-tertiary">
          {statusFilter === 'pending'
            ? 'No pending consent requests — all clear!'
            : `No ${statusFilter ?? ''} consent requests found.`}
        </div>
      )}
    </PageShell>
  )
}
