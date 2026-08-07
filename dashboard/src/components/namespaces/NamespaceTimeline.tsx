import { ArrowUpRight, Database, MessagesSquare } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import type { TimelineEntry, TimelineKind } from '@/api/namespaceTimeline'
import { PlatformBadge } from '@/components/shared/PlatformBadge'
import { useNamespaceTimeline } from '@/hooks/useNamespaceTimeline'
import { formatAbsoluteTime, formatRelativeTime } from '@/lib/utils'

type Filter = 'all' | TimelineKind

const FILTERS: { key: Filter; label: string; types?: TimelineKind[] }[] = [
  { key: 'all', label: 'All' },
  { key: 'chat', label: 'Chats', types: ['chat'] },
  { key: 'memory', label: 'Memories', types: ['memory'] },
]

export function NamespaceTimeline({ namespace }: { namespace: string }) {
  const [filter, setFilter] = useState<Filter>('all')
  const active = FILTERS.find((item) => item.key === filter)!
  const query = useNamespaceTimeline(namespace, { types: active.types })
  const items = query.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
          Timeline
        </div>
        <div
          className="ml-auto inline-flex overflow-hidden rounded-md border border-border"
          role="tablist"
          aria-label="Filter timeline by type"
        >
          {FILTERS.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={filter === item.key}
              onClick={() => setFilter(item.key)}
              className={`px-2 py-0.5 text-[11px] font-medium transition-colors ${
                filter === item.key
                  ? 'bg-brand-primaryDark text-white'
                  : 'bg-white text-content-secondary hover:bg-surface-secondary'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3">
        {query.isLoading ? (
          <div className="space-y-2" aria-label="Loading timeline">
            <div className="skeleton h-10 w-full" />
            <div className="skeleton h-10 w-11/12" />
            <div className="skeleton h-10 w-4/5" />
          </div>
        ) : query.isError ? (
          <div className="rounded-md bg-status-danger/5 px-3 py-2 text-xs text-status-danger ring-1 ring-status-danger/20">
            Could not load this namespace timeline.
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-md bg-black/[0.02] px-3 py-4 text-center text-xs text-content-tertiary ring-1 ring-black/[0.04]">
            No chats or memories in this namespace yet.
          </div>
        ) : (
          <ol className="relative ml-1 space-y-1 border-l border-black/[0.06] pl-4">
            {items.map((entry) => (
              <TimelineRow key={`${entry.kind}:${entry.id}`} entry={entry} namespace={namespace} />
            ))}
          </ol>
        )}

        {query.hasNextPage && (
          <div className="mt-3 flex justify-center">
            <button
              type="button"
              onClick={() => void query.fetchNextPage()}
              disabled={query.isFetchingNextPage}
              className="rounded-md border border-border bg-white px-3 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
            >
              {query.isFetchingNextPage ? 'Loading...' : 'Load more'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function TimelineRow({ entry, namespace }: { entry: TimelineEntry; namespace: string }) {
  const isChat = entry.kind === 'chat'
  const Icon = isChat ? MessagesSquare : Database
  return (
    <li className="relative">
      <span
        className={`absolute -left-[1.35rem] top-2 h-2 w-2 rounded-full ring-2 ring-white ${
          isChat ? 'bg-brand-primary' : 'bg-status-success'
        }`}
        aria-hidden
      />
      <div className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-surface-secondary">
        <Icon size={14} className="mt-0.5 shrink-0 text-content-tertiary" aria-hidden />
        <PlatformBadge platform={entry.platform} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="rounded bg-black/[0.04] px-1 text-[10px] font-semibold uppercase text-content-tertiary">
              {isChat ? 'chat' : entry.memory_type || 'memory'}
            </span>
            <span
              className="ml-auto shrink-0 text-[11px] text-content-tertiary"
              title={formatAbsoluteTime(entry.occurred_at)}
            >
              {formatRelativeTime(entry.occurred_at)}
            </span>
          </div>
          <div className={isChat ? 'truncate text-[13px]' : 'line-clamp-2 whitespace-pre-wrap text-[13px]'}>
            {isChat ? entry.title || '(untitled chat)' : entry.preview}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[11px] text-content-tertiary">
            {isChat && (
              <span>
                {entry.turn_count ?? 0} turns
                {entry.artifact_count ? ` / ${entry.artifact_count} files` : ''}
              </span>
            )}
            {isChat && (entry.memory_count ?? 0) > 0 && (
              <Link
                to={`/memories?namespace=${encodeURIComponent(namespace)}`}
                className="inline-flex items-center gap-0.5 text-brand-primaryDark hover:underline"
              >
                {entry.memory_count} {entry.memory_count === 1 ? 'memory' : 'memories'}
                <ArrowUpRight size={11} />
              </Link>
            )}
            {!isChat && entry.source_chat_id && (
              <Link
                to={`/chats/${entry.source_chat_id}`}
                className="inline-flex items-center gap-0.5 text-brand-primaryDark hover:underline"
              >
                from chat <ArrowUpRight size={11} />
              </Link>
            )}
          </div>
        </div>
      </div>
    </li>
  )
}
