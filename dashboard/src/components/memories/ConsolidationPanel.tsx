/**
 * Memory Vault — Consolidation Panel (KMV-E14)
 *
 * Displays per-namespace consolidation stats, policy configuration,
 * and a manual trigger button for the Admin Dashboard.
 *
 * Architecture note (displayed in UI):
 *   Memory Vault = short-term working memory (pending memories)
 *   Cognition OS = long-term semantic memory (archived memories)
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getConsolidationStats,
  getNamespacePolicy,
  updateNamespacePolicy,
  triggerConsolidation,
  type NamespacePolicy,
} from '@/api/memories'
import { cn } from '@/lib/utils'
import { RefreshCw, Settings, ChevronDown, ChevronUp, AlertCircle, CheckCircle2 } from 'lucide-react'

interface ConsolidationPanelProps {
  namespace: string
}

function WeightBar({ weight }: { weight: number }) {
  const pct = Math.round((weight ?? 1) * 100)
  const color =
    pct >= 70 ? 'bg-status-success' :
    pct >= 40 ? 'bg-status-warning' :
    'bg-status-danger'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-tertiary">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-content-tertiary">{pct}%</span>
    </div>
  )
}

function StatusPill({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div className={cn('flex flex-col items-center rounded-lg px-3 py-2', color)}>
      <span className="text-lg font-bold leading-none">{count}</span>
      <span className="mt-0.5 text-xs capitalize">{label}</span>
    </div>
  )
}

export function ConsolidationPanel({ namespace }: ConsolidationPanelProps) {
  const qc = useQueryClient()
  const [showPolicy, setShowPolicy] = useState(false)
  const [policyDraft, setPolicyDraft] = useState<Partial<NamespacePolicy>>({})
  const [triggerResult, setTriggerResult] = useState<string | null>(null)

  const stats = useQuery({
    queryKey: ['consolidation-stats', namespace],
    queryFn: () => getConsolidationStats(namespace),
    enabled: !!namespace,
  })

  const policy = useQuery({
    queryKey: ['namespace-policy', namespace],
    queryFn: () => getNamespacePolicy(namespace),
    enabled: !!namespace && showPolicy,
  })

  const updatePolicy = useMutation({
    mutationFn: (data: Partial<NamespacePolicy>) => updateNamespacePolicy(namespace, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['namespace-policy', namespace] })
      setPolicyDraft({})
    },
  })

  const trigger = useMutation({
    mutationFn: () => triggerConsolidation(namespace),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['consolidation-stats', namespace] })
      const s = data.summary
      const pushed = Object.values(s.consolidated ?? {}).reduce(
        (acc: number, v: unknown) => acc + ((v as { pushed?: number }).pushed ?? 0), 0
      )
      const archived = Object.values(s.auto_archived ?? {}).reduce(
        (acc: number, v: unknown) => acc + ((v as { auto_archived?: number }).auto_archived ?? 0), 0
      )
      setTriggerResult(
        `Epoch ${s.epoch_date}: ${pushed} pushed to Cognition OS, ${archived} auto-archived.` +
        (s.errors?.length ? ` ${s.errors.length} error(s).` : '')
      )
    },
    onError: () => setTriggerResult('Consolidation failed. Check logs.'),
  })

  const nsStats = stats.data?.stats?.[namespace]

  return (
    <div className="rounded-lg border border-border bg-white p-4">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h4 className="text-sm font-semibold text-content-primary">Consolidation</h4>
          <p className="mt-0.5 text-xs text-content-tertiary">
            Short-term → Long-term memory pipeline
          </p>
        </div>
        <button
          onClick={() => trigger.mutate()}
          disabled={trigger.isPending || !namespace}
          className="flex items-center gap-1.5 rounded-lg bg-brand-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-primary/90 disabled:opacity-50"
          title="Manually trigger consolidation for this namespace"
        >
          <RefreshCw size={12} className={cn(trigger.isPending && 'animate-spin')} />
          {trigger.isPending ? 'Running…' : 'Run Now'}
        </button>
      </div>

      {/* Architecture note */}
      <div className="mb-3 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700">
        <strong>Memory Vault</strong> is short-term working memory.{' '}
        <strong>Cognition OS</strong> is long-term semantic memory.
        Pending memories decay daily and are archived after {policy.data?.retention_days ?? 10} days.
      </div>

      {/* Stats */}
      {stats.isLoading ? (
        <div className="h-16 animate-pulse rounded-lg bg-surface-secondary" />
      ) : nsStats ? (
        <div className="mb-3 flex gap-2">
          <StatusPill label="Pending" count={nsStats.pending ?? 0} color="bg-blue-50 text-blue-700" />
          <StatusPill label="Consolidating" count={nsStats.consolidating ?? 0} color="bg-amber-50 text-amber-700" />
          <StatusPill label="Archived" count={nsStats.archived ?? 0} color="bg-green-50 text-green-700" />
        </div>
      ) : (
        <p className="mb-3 text-xs text-content-tertiary">No consolidation data yet.</p>
      )}

      {/* Average weight indicator */}
      {nsStats?.avg_weight?.pending != null && (
        <div className="mb-3 flex items-center justify-between text-xs">
          <span className="text-content-tertiary">Avg. pending weight</span>
          <WeightBar weight={nsStats.avg_weight.pending} />
        </div>
      )}

      {/* Trigger result */}
      {triggerResult && (
        <div className={cn(
          'mb-3 flex items-start gap-2 rounded-lg px-3 py-2 text-xs',
          triggerResult.includes('failed') || triggerResult.includes('error')
            ? 'bg-red-50 text-red-700'
            : 'bg-green-50 text-green-700',
        )}>
          {triggerResult.includes('failed') || triggerResult.includes('error')
            ? <AlertCircle size={12} className="mt-0.5 shrink-0" />
            : <CheckCircle2 size={12} className="mt-0.5 shrink-0" />}
          {triggerResult}
        </div>
      )}

      {/* Policy panel toggle */}
      <button
        onClick={() => setShowPolicy((v) => !v)}
        className="flex w-full items-center justify-between rounded-lg border border-border px-3 py-2 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
      >
        <span className="flex items-center gap-1.5">
          <Settings size={12} />
          Decay Policy
          {policy.data?.is_default && (
            <span className="rounded bg-surface-tertiary px-1.5 py-0.5 text-xs text-content-tertiary">default</span>
          )}
        </span>
        {showPolicy ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>

      {/* Policy editor */}
      {showPolicy && (
        <div className="mt-3 space-y-3 rounded-lg border border-border bg-surface-secondary p-3">
          {policy.isLoading ? (
            <div className="h-24 animate-pulse rounded bg-surface-tertiary" />
          ) : policy.data ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-content-secondary">
                    Decay Rate (daily)
                  </label>
                  <input
                    type="number"
                    min={0} max={1} step={0.01}
                    defaultValue={policy.data.decay_rate}
                    onChange={(e) => setPolicyDraft((d) => ({ ...d, decay_rate: parseFloat(e.target.value) }))}
                    className="w-full rounded border border-border bg-white px-2 py-1 text-xs focus:border-brand-primary focus:outline-none"
                  />
                  <p className="mt-0.5 text-xs text-content-tertiary">0.1 = 10% per day</p>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-content-secondary">
                    Retention (days)
                  </label>
                  <input
                    type="number"
                    min={1} max={365}
                    defaultValue={policy.data.retention_days}
                    onChange={(e) => setPolicyDraft((d) => ({ ...d, retention_days: parseInt(e.target.value) }))}
                    className="w-full rounded border border-border bg-white px-2 py-1 text-xs focus:border-brand-primary focus:outline-none"
                  />
                  <p className="mt-0.5 text-xs text-content-tertiary">Rolling window</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="auto-consolidate"
                  defaultChecked={policy.data.auto_consolidate}
                  onChange={(e) => setPolicyDraft((d) => ({ ...d, auto_consolidate: e.target.checked }))}
                  className="rounded border-border"
                />
                <label htmlFor="auto-consolidate" className="text-xs text-content-secondary">
                  Auto-consolidate daily (disable for stable namespaces like <code>skills</code>)
                </label>
              </div>
              <button
                onClick={() => updatePolicy.mutate(policyDraft)}
                disabled={updatePolicy.isPending || Object.keys(policyDraft).length === 0}
                className="flex items-center gap-1.5 rounded-lg bg-brand-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-primary/90 disabled:opacity-50"
              >
                {updatePolicy.isPending ? 'Saving…' : 'Save Policy'}
              </button>
              {updatePolicy.isSuccess && (
                <p className="text-xs text-status-success">Policy saved.</p>
              )}
              {updatePolicy.isError && (
                <p className="text-xs text-status-danger">Failed to save policy.</p>
              )}
            </>
          ) : null}
        </div>
      )}
    </div>
  )
}
