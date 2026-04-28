/**
 * SessionSummarySection — F12 v2
 *
 * Shows the per-session L3 rollup for a memory that belongs to a session.
 * Two bands side-by-side:
 *
 *   Session summary     — faithful narrative over memories in THIS session
 *                         only. Answers "what have we done in this session?"
 *   Cumulative summary  — faithful narrative over all namespace memories
 *                         with created_at ≤ up_to_ts (a point-in-time
 *                         snapshot of the namespace as of this session's
 *                         boundary). Answers "what was the world like when
 *                         this session ended?"
 *
 * Only renders when the memory has a session_id. Returns null otherwise
 * so the parent doesn't have to gate the import.
 */
import { History, MessageSquare, Clock } from 'lucide-react'
import { useSessionSummary } from '@/hooks/useMemories'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { MemoryLevelBadge } from '@/components/shared/MemoryLevelBadge'
import { formatRelativeTime } from '@/lib/utils'

interface Props {
  namespace: string
  sessionId: string | null | undefined
}

export function SessionSummarySection({ namespace, sessionId }: Props) {
  if (!sessionId) return null

  const { data, isLoading, isError, error } = useSessionSummary(namespace, sessionId)

  // 404 is expected until the pipeline has run for this session; render a
  // calm informative state, not a red error.
  const notFound = (error as { response?: { status?: number } })?.response?.status === 404

  return (
    <div className="space-y-2 rounded-lg border border-border bg-surface-secondary p-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-content-secondary">
        <History size={12} />
        Session rollup for{' '}
        <code className="rounded bg-white px-1 font-mono text-[10px]">{sessionId}</code>
      </div>

      {isLoading && <LoadingSkeleton lines={4} />}

      {notFound && (
        <p className="rounded-lg border border-dashed border-border bg-white p-3 text-xs italic text-content-tertiary">
          No session summary yet. Needs ≥1 memory in this session (already
          satisfied, so the background pipeline hasn't run yet — try
          refreshing in a few seconds).
        </p>
      )}

      {!notFound && isError && (
        <p className="rounded-lg border border-status-danger/30 bg-status-danger/5 p-3 text-xs text-status-danger">
          Failed to load session rollup.
        </p>
      )}

      {data && (
        <div className="space-y-3">
          {/* ── Session-only summary ─────────────────────────────── */}
          <div>
            <div className="mb-1 flex items-center gap-2 text-[11px] font-semibold text-content-secondary">
              <MessageSquare size={11} className="text-sky-600" />
              <span>In this session</span>
              <MemoryLevelBadge tier={data.session_summary_tier ?? 'L3'} />
              <span className="rounded bg-surface-tertiary px-1.5 py-0.5 text-[10px] text-content-tertiary">
                {data.session_memory_count} memor
                {data.session_memory_count === 1 ? 'y' : 'ies'}
              </span>
              {data.updated_at && (
                <span className="text-[10px] text-content-tertiary">
                  updated {formatRelativeTime(data.updated_at)}
                </span>
              )}
            </div>
            <div className="rounded-lg border border-border bg-white p-2 text-xs whitespace-pre-wrap text-content-primary">
              {data.session_summary || (
                <span className="italic text-content-tertiary">
                  (empty — session has too few memories to summarize)
                </span>
              )}
            </div>
          </div>

          {/* ── Cumulative (namespace as-of session boundary) ─────── */}
          <div>
            <div className="mb-1 flex items-center gap-2 text-[11px] font-semibold text-content-secondary">
              <Clock size={11} className="text-violet-600" />
              <span>Namespace state as of this session</span>
              <MemoryLevelBadge tier={data.cumulative_summary_tier ?? 'L3'} />
              <span className="rounded bg-surface-tertiary px-1.5 py-0.5 text-[10px] text-content-tertiary">
                {data.cumulative_memory_count} memor
                {data.cumulative_memory_count === 1 ? 'y' : 'ies'}
              </span>
              {data.up_to_ts && (
                <span className="text-[10px] text-content-tertiary">
                  up to {formatRelativeTime(data.up_to_ts)}
                </span>
              )}
            </div>
            <div className="rounded-lg border border-border bg-white p-2 text-xs whitespace-pre-wrap text-content-primary">
              {data.cumulative_summary || (
                <span className="italic text-content-tertiary">
                  (no cumulative summary — namespace needs ≥2 memories)
                </span>
              )}
            </div>
          </div>

          <p className="text-[10px] italic leading-snug text-content-tertiary">
            Two views of the same moment: the <em>session</em> band covers only
            memories tagged with this session_id; the <em>namespace</em> band
            covers every active memory in this namespace with created_at ≤
            this session's latest write, giving an answer to "what did we
            know when this session ended?"
          </p>
        </div>
      )}
    </div>
  )
}
