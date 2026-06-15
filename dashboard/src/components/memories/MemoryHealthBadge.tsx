/**
 * Memory Vault — Memory Health Badge (KMV-S15.3)
 *
 * Inline per-memory health indicator showing:
 *   - Consolidation status badge (plain-English in default view)
 *   - Weight as a visual bar OR number (user-selectable via prop)
 *   - Days until archived
 *   - Days until weight floor
 *
 * Uses a light, non-error colour palette (indigo/blue/slate/green)
 * because decay is expected behaviour, not a failure state.
 */
import { cn } from '@/lib/utils'
import { computeMemoryHealth, type MemoryHealthInfo } from '@/lib/memoryHealth'
import { useAdvancedView } from '@/contexts/AdvancedViewContext'
import { Clock, Archive, Activity } from 'lucide-react'

interface MemoryHealthBadgeProps {
  weight?: number | null
  consolidationStatus?: string | null
  createdAt?: string | null
  decayRate?: number
  retentionDays?: number
  /** 'bar' shows a visual weight bar; 'number' shows the raw float */
  weightDisplay?: 'bar' | 'number'
  /** Compact mode for list rows; expanded mode for detail panel */
  compact?: boolean
}

const tierStyles: Record<MemoryHealthInfo['tier'], {
  badge: string
  bar: string
  dot: string
}> = {
  fresh: {
    badge: 'bg-indigo-50 text-indigo-700 border-indigo-100',
    bar: 'bg-indigo-400',
    dot: 'bg-indigo-400',
  },
  active: {
    badge: 'bg-blue-50 text-blue-700 border-blue-100',
    bar: 'bg-blue-400',
    dot: 'bg-blue-400',
  },
  fading: {
    badge: 'bg-slate-100 text-slate-600 border-slate-200',
    bar: 'bg-slate-400',
    dot: 'bg-slate-400',
  },
  archived: {
    badge: 'bg-emerald-50 text-emerald-700 border-emerald-100',
    bar: 'bg-emerald-400',
    dot: 'bg-emerald-400',
  },
}

function WeightBar({
  weight,
  tier,
  display,
}: {
  weight: number
  tier: MemoryHealthInfo['tier']
  display: 'bar' | 'number'
}) {
  const pct = Math.round(weight * 100)
  const styles = tierStyles[tier]

  if (display === 'number') {
    return (
      <span className={cn('text-xs font-mono font-medium', styles.badge.split(' ')[1])}>
        {weight.toFixed(2)}
      </span>
    )
  }

  return (
    <div className="flex items-center gap-1.5" title={`Weight: ${pct}%`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
        <div
          className={cn('h-full rounded-full transition-all duration-300', styles.bar)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-slate-400">{pct}%</span>
    </div>
  )
}

function DecayPill({ icon: Icon, label, value, title }: {
  icon: React.ElementType
  label: string
  value: string
  title?: string
}) {
  return (
    <div
      className="flex items-center gap-1 rounded-full border border-slate-100 bg-slate-50 px-2 py-0.5 text-xs text-slate-500"
      title={title}
    >
      <Icon size={10} className="shrink-0" />
      <span className="hidden sm:inline">{label}:</span>
      <span className="font-medium text-slate-600">{value}</span>
    </div>
  )
}

export function MemoryHealthBadge({
  weight,
  consolidationStatus,
  createdAt,
  decayRate,
  retentionDays,
  weightDisplay = 'bar',
  compact = true,
}: MemoryHealthBadgeProps) {
  const { advanced } = useAdvancedView()
  const health = computeMemoryHealth({
    weight,
    consolidationStatus,
    createdAt,
    decayRate,
    retentionDays,
  })
  const styles = tierStyles[health.tier]

  const archiveLabel = health.daysUntilArchived === null
    ? null
    : health.daysUntilArchived === 0
    ? 'today'
    : `${health.daysUntilArchived}d`

  const floorLabel = health.daysUntilFloor === null || health.daysUntilFloor === 0
    ? null
    : `~${health.daysUntilFloor}d`

  if (compact) {
    return (
      <div className="flex flex-wrap items-center gap-1.5">
        {/* Status badge */}
        <span
          className={cn(
            'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
            styles.badge,
          )}
        >
          <span
            className={cn('h-1.5 w-1.5 rounded-full', styles.dot)}
          />
          {advanced ? (consolidationStatus ?? 'pending') : health.statusLabel}
        </span>

        {/* Weight */}
        <WeightBar weight={health.weight} tier={health.tier} display={weightDisplay} />

        {/* Decay pills — always show both */}
        {archiveLabel && (
          <DecayPill
            icon={Archive}
            label="archive"
            value={archiveLabel}
            title={`Days until archived: ${health.daysUntilArchived}`}
          />
        )}
        {floorLabel && advanced && (
          <DecayPill
            icon={Activity}
            label="floor"
            value={floorLabel}
            title={`Days until weight reaches minimum: ${health.daysUntilFloor}`}
          />
        )}
      </div>
    )
  }

  // Expanded (detail panel) view
  return (
    <div className="space-y-3 rounded-lg border border-slate-100 bg-slate-50 p-3">
      {/* Health sentence */}
      <p className="text-sm text-slate-600">{health.healthSentence}</p>

      <div className="grid grid-cols-2 gap-3">
        {/* Status */}
        <div>
          <p className="mb-1 text-xs font-medium text-slate-400">Status</p>
          <span
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium',
              styles.badge,
            )}
          >
            <span className={cn('h-1.5 w-1.5 rounded-full', styles.dot)} />
            {advanced ? (consolidationStatus ?? 'pending') : health.statusLabel}
          </span>
        </div>

        {/* Weight */}
        <div>
          <p className="mb-1 text-xs font-medium text-slate-400">Memory Strength</p>
          <WeightBar weight={health.weight} tier={health.tier} display={weightDisplay} />
          {advanced && (
            <p className="mt-0.5 text-xs text-slate-400">raw: {health.weight.toFixed(4)}</p>
          )}
        </div>

        {/* Days until archived */}
        <div>
          <p className="mb-1 text-xs font-medium text-slate-400">
            <Clock size={10} className="mr-0.5 inline" />
            Archive in
          </p>
          <p className="text-sm font-semibold text-slate-700">
            {health.daysUntilArchived === null
              ? '—'
              : health.daysUntilArchived === 0
              ? 'Today'
              : `${health.daysUntilArchived} day${health.daysUntilArchived === 1 ? '' : 's'}`}
          </p>
          {advanced && retentionDays && (
            <p className="text-xs text-slate-400">retention: {retentionDays}d</p>
          )}
        </div>

        {/* Days until weight floor */}
        <div>
          <p className="mb-1 text-xs font-medium text-slate-400">
            <Activity size={10} className="mr-0.5 inline" />
            Strength floor in
          </p>
          <p className="text-sm font-semibold text-slate-700">
            {health.daysUntilFloor === null
              ? '—'
              : health.daysUntilFloor === 0
              ? 'At floor'
              : `~${health.daysUntilFloor} day${health.daysUntilFloor === 1 ? '' : 's'}`}
          </p>
          {advanced && (
            <p className="text-xs text-slate-400">decay: {((decayRate ?? 0.1) * 100).toFixed(0)}%/day</p>
          )}
        </div>
      </div>
    </div>
  )
}
