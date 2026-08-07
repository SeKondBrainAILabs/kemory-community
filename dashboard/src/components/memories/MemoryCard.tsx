import type { MemoryResponse } from '@/api/types'
import { MemoryLevelBadge } from '@/components/shared/MemoryLevelBadge'
import { formatAbsoluteTime, formatRelativeTime } from '@/lib/utils'

/**
 * S9N-6167: compact card representation of a memory for the mobile
 * (<768px) list, where the full DataTable is unreadable. Shows a content
 * preview, namespace + type + tier chips, a relevance chip during search,
 * and the age. The whole card is a button so it opens the detail sheet.
 */
export function MemoryCard({
  memory,
  onClick,
  timeField = 'occurred',
}: {
  memory: MemoryResponse
  onClick: (m: MemoryResponse) => void
  timeField?: 'occurred' | 'created' | 'updated'
}) {
  const rel = memory.similarity_score
  const ts =
    timeField === 'occurred'
      ? (memory.occurred_at ?? memory.created_at)
      : timeField === 'created'
        ? memory.created_at
        : memory.updated_at

  return (
    <button
      type="button"
      onClick={() => onClick(memory)}
      className="w-full rounded-lg border border-border bg-white p-3 text-left transition-colors hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="line-clamp-3 text-sm text-content-primary">{memory.content}</p>
        {rel != null && (
          <span className="mt-0.5 shrink-0 rounded bg-brand-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-brand-primaryDark">
            {Math.round(rel * 100)}%
          </span>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        <span className="max-w-[45%] truncate rounded bg-surface-tertiary px-1.5 py-0.5 text-content-secondary">
          {memory.namespace}
        </span>
        <span className="rounded bg-surface-tertiary px-1.5 py-0.5 text-content-secondary">
          {memory.content_type}
        </span>
        <MemoryLevelBadge
          tier={(memory as MemoryResponse & { compression_tier?: string }).compression_tier ?? 'L1'}
        />
        <span className="ml-auto text-content-tertiary" title={formatAbsoluteTime(ts)}>
          {formatRelativeTime(ts)}
        </span>
      </div>
    </button>
  )
}
