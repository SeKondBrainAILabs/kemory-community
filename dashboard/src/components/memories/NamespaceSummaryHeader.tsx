/**
 * Memory Vault — Namespace Summary Header (KMV-S15.2)
 *
 * A compact, collapsible header above the memory list that shows:
 *   - Total memory count with status breakdown
 *   - Average weight bar
 *   - Plain-English health sentence
 *   - Expandable consolidation controls (policy + manual trigger)
 *
 * Replaces the standalone ConsolidationPanel with an integrated header
 * so everything is visible in one view without scrolling.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, RefreshCw, Settings, Brain, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  getConsolidationStats,
  getNamespacePolicy,
  updateNamespacePolicy,
  triggerConsolidation,
  type NamespacePolicy,
} from '@/api/memories'
import { useAdvancedView } from '@/contexts/AdvancedViewContext'

interface NamespaceSummaryHeaderProps {
  namespace: string
  totalMemories?: number
}

function StatChip({
  label,
  count,
  className,
}: {
  label: string
  count: number
  className?: string
}) {
  return (
    <div className={cn('flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs', className)}>
      <span className="font-semibold">{count}</span>
      <span className="text-opacity-80">{label}</span>
    </div>
  )
}

function AvgWeightBar({ weight }: { weight: number }) {
  const pct = Math.round(weight * 100)
  const barColor =
    pct >= 70 ? 'bg-indigo-400' :
    pct >= 40 ? 'bg-blue-400' :
    'bg-slate-400'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100">
        <div
          className={cn('h-full rounded-full transition-all', barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-slate-400">{pct}% avg</span>
    </div>
  )
}

function healthSentenceForNamespace(
  pending: number,
  archived: number,
  avgWeight: number,
): string {
  const total = pending + archived
  if (total === 0) return 'No memories in this namespace yet.'
  const pct = Math.round(avgWeight * 100)
  const archivePart = archived > 0
    ? ` ${archived} have moved to long-term memory.`
    : ''
  if (pct >= 70) return `${pending} active memories at ${pct}% average strength.${archivePart}`
  if (pct >= 40) return `${pending} active memories at ${pct}% strength — some are fading.${archivePart}`
  return `${pending} active memories at ${pct}% strength — most will be archived soon.${archivePart}`
}

export function NamespaceSummaryHeader({
  namespace,
  totalMemories,
}: NamespaceSummaryHeaderProps) {
  const { advanced } = useAdvancedView()
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [showPolicy, setShowPolicy] = useState(false)
  const [policyDraft, setPolicyDraft] = useState<Partial<NamespacePolicy>>({})
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null)

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
      setTriggerMsg(`Done — ${pushed} memories synced to long-term memory.`)
    },
    onError: () => setTriggerMsg('Sync failed. Check logs.'),
  })

  const nsStats = stats.data?.stats?.[namespace]
  const pending = nsStats?.pending ?? 0
  const consolidating = nsStats?.consolidating ?? 0
  const archived = nsStats?.archived ?? 0
  const avgWeight = nsStats?.avg_weight?.pending ?? 1.0

  const sentence = healthSentenceForNamespace(pending, archived, avgWeight)

  return (
    <div className="rounded-lg border border-slate-100 bg-white shadow-sm">
      {/* ── Compact header row ── */}
      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          {/* Memory counts */}
          <div className="flex items-center gap-1.5">
            {pending > 0 && (
              <StatChip
                label="active"
                count={pending}
                className="bg-blue-50 text-blue-700"
              />
            )}
            {consolidating > 0 && (
              <StatChip
                label="syncing"
                count={consolidating}
                className="bg-amber-50 text-amber-700"
              />
            )}
            {archived > 0 && (
              <StatChip
                label="archived"
                count={archived}
                className="bg-emerald-50 text-emerald-700"
              />
            )}
            {totalMemories !== undefined && advanced && (
              <span className="text-xs text-slate-400">({totalMemories} total)</span>
            )}
          </div>

          {/* Avg weight bar */}
          {nsStats && <AvgWeightBar weight={avgWeight} />}

          {/* Health sentence — hidden in advanced mode (too verbose) */}
          {!advanced && (
            <p className="hidden text-xs text-slate-500 md:block">{sentence}</p>
          )}
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => trigger.mutate()}
            disabled={trigger.isPending || !namespace}
            className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            title="Sync this namespace to long-term memory now"
          >
            <RefreshCw size={11} className={cn(trigger.isPending && 'animate-spin')} />
            <span className="hidden sm:inline">Sync</span>
          </button>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            title={expanded ? 'Collapse details' : 'Expand details'}
          >
            <Settings size={11} />
            {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        </div>
      </div>

      {/* ── Trigger result ── */}
      {triggerMsg && (
        <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">
          {triggerMsg}
        </div>
      )}

      {/* ── Expanded section ── */}
      {expanded && (
        <div className="border-t border-slate-100 px-4 py-3 space-y-3">
          {/* Architecture note */}
          <div className="flex items-start gap-2 rounded-lg bg-indigo-50 px-3 py-2 text-xs text-indigo-700">
            <Brain size={12} className="mt-0.5 shrink-0" />
            <span>
              <strong>Memory Vault</strong> holds short-term working memory.
              {' '}<strong>Cognition OS</strong> holds long-term semantic memory.
              Memories decay daily and are archived after {policy.data?.retention_days ?? 10} days.
            </span>
          </div>

          {/* Policy toggle */}
          <button
            onClick={() => setShowPolicy((v) => !v)}
            className="flex w-full items-center justify-between rounded-lg border border-slate-100 px-3 py-2 text-xs font-medium text-slate-500 hover:bg-slate-50"
          >
            <span className="flex items-center gap-1.5">
              <Clock size={11} />
              Decay Policy
              {policy.data?.is_default && (
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-400">default</span>
              )}
            </span>
            {showPolicy ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>

          {showPolicy && (
            <div className="rounded-lg border border-slate-100 bg-slate-50 p-3 space-y-3">
              {policy.isLoading ? (
                <div className="h-20 animate-pulse rounded bg-slate-100" />
              ) : policy.data ? (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1 block text-xs font-medium text-slate-500">
                        Decay Rate (daily)
                      </label>
                      <input
                        type="number" min={0} max={1} step={0.01}
                        defaultValue={policy.data.decay_rate}
                        onChange={(e) => setPolicyDraft((d) => ({ ...d, decay_rate: parseFloat(e.target.value) }))}
                        className="w-full rounded border border-slate-200 bg-white px-2 py-1 text-xs focus:border-indigo-400 focus:outline-none"
                      />
                      <p className="mt-0.5 text-xs text-slate-400">e.g. 0.1 = 10%/day</p>
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium text-slate-500">
                        Retention (days)
                      </label>
                      <input
                        type="number" min={1} max={365}
                        defaultValue={policy.data.retention_days}
                        onChange={(e) => setPolicyDraft((d) => ({ ...d, retention_days: parseInt(e.target.value) }))}
                        className="w-full rounded border border-slate-200 bg-white px-2 py-1 text-xs focus:border-indigo-400 focus:outline-none"
                      />
                      <p className="mt-0.5 text-xs text-slate-400">rolling window</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox" id="auto-consolidate-ns"
                      defaultChecked={policy.data.auto_consolidate}
                      onChange={(e) => setPolicyDraft((d) => ({ ...d, auto_consolidate: e.target.checked }))}
                      className="rounded border-slate-300"
                    />
                    <label htmlFor="auto-consolidate-ns" className="text-xs text-slate-500">
                      Auto-sync daily
                    </label>
                  </div>
                  <button
                    onClick={() => updatePolicy.mutate(policyDraft)}
                    disabled={updatePolicy.isPending || Object.keys(policyDraft).length === 0}
                    className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {updatePolicy.isPending ? 'Saving…' : 'Save Policy'}
                  </button>
                  {updatePolicy.isSuccess && (
                    <p className="text-xs text-emerald-600">Policy saved.</p>
                  )}
                </>
              ) : null}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
