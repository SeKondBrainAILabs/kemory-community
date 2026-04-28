/**
 * MemoryLevelBadge — F12
 *
 * Displays a colour-coded badge for a memory's compression tier:
 *   L1   — Raw observation (slate)
 *   L2   — AAAK lossless encoding (blue)
 *   L3   — Groq narrative summary (sky) — faithful prose, namespace-wide
 *   L3.1 — LLM-synthesized concept (violet) — opinionated merge
 *   L4   — Cognition OS graph-augmented (indigo) — concepts + graph entities
 *
 * Story: F12-US-001 + v0.13.1 (L3 narrative)
 */
import { cn } from '@/lib/utils'

type Tier = 'L1' | 'L2' | 'L3' | 'L3.1' | 'L4'

interface TierStyle {
  bg: string
  text: string
  border: string
  dot: string
  label: string
  description: string
}

const TIER_STYLES: Record<Tier, TierStyle> = {
  L1: {
    bg: 'bg-slate-50',
    text: 'text-slate-700',
    border: 'border-slate-200',
    dot: 'bg-slate-400',
    label: 'L1',
    description: 'Raw observation — uncompressed memory record',
  },
  L2: {
    bg: 'bg-blue-50',
    text: 'text-blue-700',
    border: 'border-blue-200',
    dot: 'bg-blue-500',
    label: 'L2',
    description: 'AAAK lossless encoding — field-aliased, phrase-substituted',
  },
  L3: {
    bg: 'bg-sky-50',
    text: 'text-sky-700',
    border: 'border-sky-200',
    dot: 'bg-sky-500',
    label: 'L3',
    description: 'Narrative summary — faithful Groq LLM prose rollup of the namespace',
  },
  'L3.1': {
    bg: 'bg-violet-50',
    text: 'text-violet-700',
    border: 'border-violet-200',
    dot: 'bg-violet-500',
    label: 'L3.1',
    description: 'Concept synthesis — LLM-merged, opinionated position from similar memories',
  },
  L4: {
    bg: 'bg-indigo-50',
    text: 'text-indigo-700',
    border: 'border-indigo-200',
    dot: 'bg-indigo-500',
    label: 'L4',
    description: 'Cognition OS graph-augmented — concepts enriched with graph entities',
  },
}

interface MemoryLevelBadgeProps {
  tier: Tier | string
  className?: string
  showDot?: boolean
}

export function MemoryLevelBadge({
  tier,
  className,
  showDot = true,
}: MemoryLevelBadgeProps) {
  const style = TIER_STYLES[tier as Tier] ?? TIER_STYLES.L1
  return (
    <span
      title={style.description}
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold',
        style.bg,
        style.text,
        style.border,
        className,
      )}
    >
      {showDot && (
        <span className={cn('h-1.5 w-1.5 rounded-full', style.dot)} />
      )}
      {style.label}
    </span>
  )
}

/**
 * MemoryLevelLegend — compact horizontal legend for the filter bar.
 */
export function MemoryLevelLegend() {
  return (
    <div className="flex items-center gap-2 text-xs text-content-tertiary">
      <span className="font-medium">Tier:</span>
      {(['L1', 'L2', 'L3', 'L3.1', 'L4'] as Tier[]).map((t) => (
        <span key={t} className="flex items-center gap-1">
          <MemoryLevelBadge tier={t} />
          <span className="hidden sm:inline">{TIER_STYLES[t].description.split(' — ')[0]}</span>
        </span>
      ))}
    </div>
  )
}
