/**
 * MemoryLevelsSection — per-memory L2 / L3 / L3.1 / L4 view for the Memory
 * Detail panel.
 *
 * Architectural note:
 *   L2 (AAAK), L3 (Groq narrative summary), L3.1 (concept synthesis), and
 *   L4 (Cognition OS graph-augmented) are all *namespace-level* artefacts,
 *   not per-memory ones. So we show the namespace-wide view for each, but
 *   highlight this memory's contribution where possible: for L3.1, concepts
 *   whose `source_memory_ids` include the selected memory_id are called out
 *   as "includes this memory".
 *
 * Each section is collapsible and lazy-loaded (only fetches when opened).
 */
import { useState } from 'react'
import { ChevronDown, ChevronUp, Layers } from 'lucide-react'
import { useMemoryLevel, useNamespaceSummary } from '@/hooks/useMemories'
import { formatRelativeTime } from '@/lib/utils'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { MemoryLevelBadge } from '@/components/shared/MemoryLevelBadge'

interface MemoryLevelsSectionProps {
  namespace: string
  memoryId: string
}

function SectionHeader({
  tier,
  title,
  subtitle,
  open,
  onToggle,
}: {
  tier: 'L1' | 'L2' | 'L3' | 'L3.1' | 'L4'
  title: string
  subtitle?: string
  open: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center justify-between rounded-lg border border-border bg-white px-3 py-2 text-left hover:bg-surface-secondary"
    >
      <div className="flex items-center gap-2 text-xs">
        <MemoryLevelBadge tier={tier} />
        <span className="font-semibold text-content-primary">{title}</span>
        {subtitle && <span className="text-content-tertiary">{subtitle}</span>}
      </div>
      {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
    </button>
  )
}

function L2View({ namespace }: { namespace: string }) {
  const { data, isLoading, isError } = useMemoryLevel(namespace, 'aaak')
  if (isLoading) return <LoadingSkeleton lines={3} />
  if (isError) return <p className="text-xs text-status-danger">Failed to load AAAK encoding.</p>
  if (!data) return null
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="rounded bg-surface-tertiary px-2 py-0.5">
          Sources: <span className="font-semibold">{data.source_count}</span>
        </span>
        {data.compressed_size != null && (
          <span className="rounded bg-surface-tertiary px-2 py-0.5">
            Size: <span className="font-semibold">{data.compressed_size}b</span>
          </span>
        )}
        {data.ratio != null && (
          <span className="rounded bg-brand-primary/10 px-2 py-0.5 text-brand-primary">
            <span className="font-semibold">{data.ratio}×</span> compression
          </span>
        )}
      </div>
      <pre className="max-h-64 overflow-auto rounded-lg border border-border bg-surface-tertiary p-2 text-xs font-mono whitespace-pre-wrap">
        {data.content ?? '(empty)'}
      </pre>
    </div>
  )
}

function L3NarrativeView({ namespace }: { namespace: string }) {
  // L3 narrative summary is the NamespacePolicy.consolidated_summary with
  // tier="L3". Reuses the existing namespace-summary endpoint so no new
  // backend call is needed.
  const { data, isLoading, isError } = useNamespaceSummary(namespace)
  if (isLoading) return <LoadingSkeleton lines={3} />
  if (isError) return <p className="text-xs text-status-danger">Failed to load narrative summary.</p>
  if (!data) return null

  const tier = data.consolidated_summary_tier
  const summary = data.consolidated_summary
  // Only show the L3 body when the stored tier is actually L3. If L3.1 has
  // run and overwritten the slot, we tell the user to open the L3.1 section
  // instead — we don't have the pre-L3.1 narrative text cached.
  if (!summary) {
    return (
      <p className="text-xs italic text-content-tertiary">
        No narrative summary yet. Needs ≥2 memories in this namespace.
      </p>
    )
  }
  if (tier === 'L3.1' || tier === 'L4') {
    return (
      <p className="text-xs italic text-content-tertiary">
        Superseded by {tier}. Open the {tier} section below to view the
        current consolidated summary.
      </p>
    )
  }
  return (
    <div className="space-y-2 text-xs">
      <div className="flex flex-wrap gap-2">
        {data.consolidated_summary_updated_at && (
          <span className="rounded bg-surface-tertiary px-2 py-0.5 text-content-tertiary">
            updated {formatRelativeTime(data.consolidated_summary_updated_at)}
          </span>
        )}
        <span className="rounded bg-sky-50 px-2 py-0.5 text-sky-700">
          Groq narrative (faithful, namespace-wide)
        </span>
      </div>
      <div className="rounded-lg border border-border bg-white p-2 whitespace-pre-wrap text-content-primary">
        {summary}
      </div>
    </div>
  )
}

function L4View({ namespace }: { namespace: string }) {
  const { data, isLoading, isError } = useMemoryLevel(namespace, 'cognition')
  if (isLoading) return <LoadingSkeleton lines={3} />
  if (isError) return <p className="text-xs text-status-danger">Failed to load cognition entities.</p>
  if (!data) return null
  const entities = (data.graph_entities ?? []) as Array<{
    entity_id: string
    title: string
    content: string
    score: number
    source: string
  }>
  if (!data.cognition_os_available) {
    return (
      <p className="text-xs italic text-content-tertiary">
        Cognition OS is not available — L4 falls back to L3.1 concepts only.
      </p>
    )
  }
  if (entities.length === 0) {
    return (
      <p className="text-xs italic text-content-tertiary">
        No graph entities linked yet for this namespace.
      </p>
    )
  }
  return (
    <div className="space-y-2 text-xs">
      <span className="rounded bg-indigo-50 px-2 py-0.5 text-indigo-700">
        {entities.length} graph entit{entities.length === 1 ? 'y' : 'ies'}
      </span>
      <div className="space-y-1.5">
        {entities.slice(0, 5).map((e) => (
          <div key={e.entity_id} className="rounded-lg border border-border bg-white p-2">
            <div className="flex items-center justify-between">
              <div className="font-semibold text-content-primary">{e.title}</div>
              <span className="text-content-tertiary">score {(e.score || 0).toFixed(2)}</span>
            </div>
            {e.content && (
              <div className="mt-0.5 line-clamp-2 text-content-secondary">{e.content}</div>
            )}
          </div>
        ))}
        {entities.length > 5 && (
          <p className="text-content-tertiary">+{entities.length - 5} more</p>
        )}
      </div>
    </div>
  )
}

function L3View({ namespace, memoryId }: { namespace: string; memoryId: string }) {
  const { data, isLoading, isError } = useMemoryLevel(namespace, 'concept')
  if (isLoading) return <LoadingSkeleton lines={4} />
  if (isError) return <p className="text-xs text-status-danger">Failed to load concept synthesis.</p>
  if (!data) return null
  // Concept shape is produced by memory_vault/compression/llm_client.py:Concept.to_dict()
  //   { name, synthesis, source_memory_ids, directional, positions_merged, source, synthesis_unavailable }
  const concepts = (data.concepts ?? []) as Array<{
    name?: string
    synthesis?: string
    source_memory_ids?: string[]
    directional?: boolean
    positions_merged?: number
    source?: string
    synthesis_unavailable?: boolean
  }>
  if (concepts.length === 0) {
    return (
      <p className="text-xs italic text-content-tertiary">
        No concepts synthesized yet for this namespace. L3.1 requires ≥3
        memories <em>and</em> at least one cluster of near-duplicates.
      </p>
    )
  }
  const includingThis = concepts.filter((c) =>
    (c.source_memory_ids ?? []).includes(memoryId),
  )
  const otherConcepts = concepts.filter((c) =>
    !(c.source_memory_ids ?? []).includes(memoryId),
  )

  const renderConcept = (c: typeof concepts[number], idx: number, highlight: boolean) => {
    const sources = c.source_memory_ids ?? []
    const title = c.name && c.name !== 'empty' ? c.name : `concept ${idx + 1}`
    const body = c.synthesis || ''
    const isPassthrough = c.source === 'raw_passthrough'
    const isFallback = c.source === 'raw_fallback' || c.synthesis_unavailable
    return (
      <div
        key={(c.name || '') + '-' + idx}
        className={
          highlight
            ? 'rounded-lg border border-violet-200 bg-violet-50/50 p-2'
            : 'rounded-lg border border-border bg-white p-2'
        }
      >
        <div className="flex items-start justify-between gap-2">
          <div className="font-semibold text-content-primary">{title}</div>
          <div className="flex flex-wrap gap-1">
            {c.directional && (
              <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
                directional
              </span>
            )}
            {isPassthrough && (
              <span className="rounded bg-surface-tertiary px-1.5 py-0.5 text-[10px] text-content-tertiary">
                single-memory pass-through
              </span>
            )}
            {isFallback && (
              <span className="rounded bg-status-danger/10 px-1.5 py-0.5 text-[10px] text-status-danger">
                LLM unavailable
              </span>
            )}
          </div>
        </div>
        {body ? (
          <div className="mt-0.5 whitespace-pre-wrap text-content-secondary">{body}</div>
        ) : (
          <div className="mt-0.5 italic text-content-tertiary">(empty synthesis)</div>
        )}
        <div className="mt-1 text-content-tertiary">
          {sources.length} source memor{sources.length === 1 ? 'y' : 'ies'}
          {c.positions_merged != null && c.positions_merged !== sources.length && (
            <> · {c.positions_merged} positions merged</>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3 text-xs">
      <div className="flex flex-wrap gap-2">
        <span className="rounded bg-surface-tertiary px-2 py-0.5">
          {concepts.length} concept{concepts.length === 1 ? '' : 's'} total
        </span>
        <span className="rounded bg-violet-50 px-2 py-0.5 text-violet-700">
          {includingThis.length} include this memory
        </span>
      </div>

      {includingThis.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-semibold text-violet-700">
            Includes this memory
          </div>
          <div className="space-y-1.5">
            {includingThis.map((c, i) => renderConcept(c, i, true))}
          </div>
        </div>
      )}

      {otherConcepts.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-semibold text-content-tertiary">
            Other concepts in this namespace
          </div>
          <div className="space-y-1.5">
            {otherConcepts.slice(0, 5).map((c, i) => renderConcept(c, i, false))}
            {otherConcepts.length > 5 && (
              <p className="text-content-tertiary">+{otherConcepts.length - 5} more</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

type OpenSection = 'l2' | 'l3' | 'l3_1' | 'l4' | null

export function MemoryLevelsSection({ namespace, memoryId }: MemoryLevelsSectionProps) {
  const [open, setOpen] = useState<OpenSection>(null)
  const toggle = (s: Exclude<OpenSection, null>) => setOpen(open === s ? null : s)

  return (
    <div className="space-y-2 rounded-lg border border-border bg-surface-secondary p-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-content-secondary">
        <Layers size={12} />
        Memory Levels for{' '}
        <code className="rounded bg-white px-1 font-mono text-[10px]">{namespace}</code>
      </div>

      <SectionHeader
        tier="L2"
        title="Compressed (AAAK)"
        subtitle="lossless, field-aliased"
        open={open === 'l2'}
        onToggle={() => toggle('l2')}
      />
      {open === 'l2' && (
        <div className="pl-1">
          <L2View namespace={namespace} />
        </div>
      )}

      <SectionHeader
        tier="L3"
        title="Narrative summary"
        subtitle="Groq LLM, faithful prose"
        open={open === 'l3'}
        onToggle={() => toggle('l3')}
      />
      {open === 'l3' && (
        <div className="pl-1">
          <L3NarrativeView namespace={namespace} />
        </div>
      )}

      <SectionHeader
        tier="L3.1"
        title="Concepts (synthesized)"
        subtitle="LLM-merged"
        open={open === 'l3_1'}
        onToggle={() => toggle('l3_1')}
      />
      {open === 'l3_1' && (
        <div className="pl-1">
          <L3View namespace={namespace} memoryId={memoryId} />
        </div>
      )}

      <SectionHeader
        tier="L4"
        title="Cognition OS"
        subtitle="concepts + graph entities"
        open={open === 'l4'}
        onToggle={() => toggle('l4')}
      />
      {open === 'l4' && (
        <div className="pl-1">
          <L4View namespace={namespace} />
        </div>
      )}

      <div className="mt-2 space-y-1 rounded-md bg-white/60 p-2 text-[10px] leading-snug text-content-tertiary ring-1 ring-black/[0.04]">
        <div>
          <strong className="text-content-secondary">L2</strong> · AAAK,
          lossless field-aliased compression — every memory (threshold 1).
        </div>
        <div>
          <strong className="text-content-secondary">L3</strong> · Groq LLM
          narrative summary — <em>faithful prose, no opinions, notes
          conflicts</em>. Namespace needs ≥2 memories.
        </div>
        <div>
          <strong className="text-content-secondary">L3.1</strong> ·
          LLM-merged concept extraction — <em>clusters similar memories
          and picks a current value</em>. Requires ≥3 memories AND at
          least one cluster of near-duplicates (cosine ≥0.85). Writes
          searchable concept rows, unlike L3.
        </div>
        <div>
          <strong className="text-content-secondary">L4</strong> · L3.1
          augmented with Cognition OS graph entities. Skipped when Cognition
          OS is offline.
        </div>
        <div className="pt-1 italic">
          All four are namespace-wide views. This memory's Tier badge above
          shows its own compression state.
        </div>
      </div>
    </div>
  )
}
