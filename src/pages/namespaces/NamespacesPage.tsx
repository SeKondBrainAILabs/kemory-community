/**
 * Kemory — Namespaces Page (v3.31.2: tabs + search)
 *
 * Now shows BOTH memory and chat content per namespace. Three top-level
 * tabs scope the list:
 *   All       — every namespace that has anything (memories OR chats)
 *   Memories  — only namespaces with at least one memory
 *   Chats     — only namespaces with at least one chat
 *
 * A search input above the list filters namespace names by substring
 * (case-insensitive, live).
 *
 * Detail drawer links to both the Memory Explorer and the Chats list
 * pre-filtered to the namespace, so you can dive into either store.
 *
 * Chat-count aggregation: we ask /api/v1/chats?limit=200 once and group
 * client-side. v1 caps at 200 chats per user — fine while we're at
 * single-user scale; if this grows we'll add a dedicated
 * /api/v1/chats/namespaces aggregate endpoint in a future patch.
 */
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  FolderTree,
  Sparkles,
  Link2,
  ChevronRight,
  Database,
  MessagesSquare,
  Search,
} from 'lucide-react'
import * as Tabs from '@radix-ui/react-tabs'
import { PageShell } from '@/components/layout/PageShell'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { useNamespaces, useNamespaceSummary } from '@/hooks/useMemories'
import { useChatList } from '@/hooks/useChats'
import type { NamespaceInfo } from '@/api/types'
import { formatRelativeTime, cn } from '@/lib/utils'

// ─── Combined namespace row shape ───────────────────────────────────

interface CombinedNamespace {
  namespace: string
  memory_count: number
  chat_count: number
  // From the memory NamespaceInfo (only populated when memory_count > 0):
  description?: string | null
  consolidated_summary?: string | null
  consolidated_summary_tier?: string | null
  consolidated_summary_updated_at?: string | null
  related_namespaces?: NamespaceInfo['related_namespaces']
}

type TabKey = 'all' | 'memories' | 'chats'

// ─── Badges ─────────────────────────────────────────────────────────

function TierBadge({ tier }: { tier: string | null | undefined }) {
  if (!tier) {
    return (
      <span className="inline-flex items-center rounded-full bg-black/[0.04] px-2 py-0.5 text-[10px] font-medium text-content-tertiary">
        no summary
      </span>
    )
  }
  const color =
    tier === 'L3.1'
      ? 'bg-indigo-50 text-indigo-700 ring-indigo-200'
      : tier === 'L3'
        ? 'bg-sky-50 text-sky-700 ring-sky-200'
        : tier === 'L3.0'
          ? 'bg-amber-50 text-amber-700 ring-amber-200'
          : 'bg-black/[0.04] text-content-secondary ring-black/[0.06]'
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1',
        color,
      )}
    >
      <Sparkles size={10} />
      {tier}
    </span>
  )
}

function CountChip({
  icon: Icon,
  value,
  label,
  muted,
}: {
  icon: typeof Database
  value: number
  label: string
  muted?: boolean
}) {
  if (value === 0 && muted) return null
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1',
        value > 0
          ? 'bg-white text-content-primary ring-black/[0.08]'
          : 'bg-black/[0.03] text-content-tertiary ring-black/[0.04]',
      )}
      title={`${value} ${label}`}
    >
      <Icon size={11} />
      <span className="tabular-nums">{value.toLocaleString()}</span>
    </span>
  )
}

// ─── Detail drawer ─────────────────────────────────────────────────

function NamespaceDetailDrawer({
  ns,
}: {
  ns: CombinedNamespace
}) {
  const { data, isLoading } = useNamespaceSummary(ns.namespace)
  const memoryCount = ns.memory_count
  const chatCount = ns.chat_count

  if (isLoading && memoryCount > 0) {
    return <div className="py-6"><LoadingSkeleton /></div>
  }

  // The summary endpoint only returns data for memory-backed namespaces.
  // For chat-only namespaces we render a slim variant that still shows
  // the related links + counts, just without the consolidated summary.
  const desc = data?.description ?? ns.description ?? null
  const summary = data?.consolidated_summary ?? ns.consolidated_summary ?? null
  const summaryTier =
    data?.consolidated_summary_tier ?? ns.consolidated_summary_tier ?? null
  const summaryUpdated =
    data?.consolidated_summary_updated_at ?? ns.consolidated_summary_updated_at ?? null
  const related = data?.related_namespaces ?? ns.related_namespaces ?? []

  return (
    <div className="space-y-4 px-6 py-5">
      <div className="flex flex-wrap items-center gap-2">
        <CountChip icon={Database} value={memoryCount} label="memories" />
        <CountChip icon={MessagesSquare} value={chatCount} label="chats" />
      </div>

      <div>
        <div className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
          Description
        </div>
        <div className="mt-1 whitespace-pre-wrap text-sm text-content-primary">
          {desc || <span className="text-content-tertiary">(none)</span>}
        </div>
      </div>

      {memoryCount > 0 && (
        <div>
          <div className="flex items-center gap-2">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
              Consolidated summary
            </div>
            <TierBadge tier={summaryTier} />
            {summaryUpdated ? (
              <span className="text-[11px] text-content-tertiary">
                updated {formatRelativeTime(summaryUpdated)}
              </span>
            ) : null}
          </div>
          <div className="mt-1 whitespace-pre-wrap rounded-md bg-black/[0.02] p-3 text-sm text-content-primary ring-1 ring-black/[0.04]">
            {summary || (
              <span className="text-content-tertiary">
                {memoryCount < 2
                  ? `Not yet consolidated. Needs ≥2 memories for L3 summary (have ${memoryCount}).`
                  : memoryCount < 3
                    ? 'Pending — L3 narrative summary has not yet run for this namespace. It should appear shortly after the next write.'
                    : 'Pending — the compression pipeline has not produced a summary yet despite sufficient memories. The background job may not have run; try creating a new memory or running the backfill script.'}
              </span>
            )}
          </div>
        </div>
      )}

      {related && related.length > 0 && (
        <div>
          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
            <Link2 size={12} /> Related namespaces (auto-detected)
          </div>
          <ul className="mt-2 space-y-1">
            {related.map((r, idx) => (
              <li
                key={`${r.namespace}-${idx}`}
                className="flex items-center justify-between rounded-md bg-white px-3 py-1.5 text-[12px] ring-1 ring-black/[0.04]"
              >
                <span className="font-mono text-content-primary">{r.namespace}</span>
                <span className="text-content-tertiary">
                  {r.similarity != null ? `similarity ${(r.similarity * 100).toFixed(0)}%` : '—'}
                  {r.action ? ` · ${r.action}` : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-3 text-[12px] font-medium">
        {memoryCount > 0 && (
          <Link
            to={`/memories?namespace=${encodeURIComponent(ns.namespace)}`}
            className="inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-700"
          >
            <Database size={12} /> Open in Memory Explorer <ChevronRight size={14} />
          </Link>
        )}
        {chatCount > 0 && (
          <Link
            to={`/chats?namespace=${encodeURIComponent(ns.namespace)}`}
            className="inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-700"
          >
            <MessagesSquare size={12} /> Open in Chats <ChevronRight size={14} />
          </Link>
        )}
      </div>
    </div>
  )
}

// ─── Row ───────────────────────────────────────────────────────────

function NamespaceRow({
  ns,
  expanded,
  onToggle,
  activeTab,
}: {
  ns: CombinedNamespace
  expanded: boolean
  onToggle: () => void
  activeTab: TabKey
}) {
  const relatedCount = ns.related_namespaces?.length ?? 0
  const summaryPreview = (ns.consolidated_summary || '').slice(0, 180)

  // Right-side metric depends on tab: when filtered to one type, show
  // just that count prominently. "All" shows both as chips.
  const right =
    activeTab === 'memories'
      ? { value: ns.memory_count, label: 'memories' }
      : activeTab === 'chats'
        ? { value: ns.chat_count, label: 'chats' }
        : null

  return (
    <div className="border-b border-black/[0.04] bg-white">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-4 px-4 py-3 text-left hover:bg-black/[0.015]"
      >
        <ChevronRight
          size={14}
          className={cn(
            'mt-1 shrink-0 text-content-tertiary transition-transform',
            expanded ? 'rotate-90' : 'rotate-0',
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <FolderTree size={14} className="text-content-tertiary shrink-0" />
            <div className="truncate font-mono text-[13px] font-semibold text-content-primary">
              {ns.namespace}
            </div>
            {ns.memory_count > 0 && <TierBadge tier={ns.consolidated_summary_tier} />}
            {relatedCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-amber-200">
                <Link2 size={10} /> {relatedCount} related
              </span>
            )}
            {activeTab === 'all' && (
              <>
                <CountChip icon={Database} value={ns.memory_count} label="memories" muted />
                <CountChip
                  icon={MessagesSquare}
                  value={ns.chat_count}
                  label="chats"
                  muted
                />
              </>
            )}
          </div>
          {ns.description ? (
            <div className="mt-0.5 truncate text-[12px] text-content-secondary">
              {ns.description}
            </div>
          ) : null}
          {summaryPreview ? (
            <div className="mt-1 line-clamp-2 text-[12px] text-content-tertiary">
              {summaryPreview}
              {(ns.consolidated_summary || '').length > 180 ? '…' : ''}
            </div>
          ) : null}
        </div>
        {right && (
          <div className="text-right">
            <div className="font-mono text-[13px] font-semibold text-content-primary tabular-nums">
              {right.value.toLocaleString()}
            </div>
            <div className="text-[10px] uppercase tracking-wider text-content-tertiary">
              {right.label}
            </div>
          </div>
        )}
      </button>

      {expanded && (
        <div className="border-t border-black/[0.04] bg-black/[0.015]">
          <NamespaceDetailDrawer ns={ns} />
        </div>
      )}
    </div>
  )
}

// ─── Tabs trigger styling ──────────────────────────────────────────

function TabTrigger({
  value,
  label,
  count,
}: {
  value: TabKey
  label: string
  count: number
}) {
  return (
    <Tabs.Trigger
      value={value}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors',
        'text-content-secondary hover:text-content-primary',
        'data-[state=active]:bg-white data-[state=active]:text-content-primary',
        'data-[state=active]:shadow-[0_1px_2px_rgba(0,0,0,0.04)] data-[state=active]:ring-1 data-[state=active]:ring-black/[0.06]',
      )}
    >
      {label}
      <span className="rounded-full bg-black/[0.06] px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-content-tertiary">
        {count}
      </span>
    </Tabs.Trigger>
  )
}

// ─── Page ──────────────────────────────────────────────────────────

export function NamespacesPage() {
  const memNs = useNamespaces()
  // Pull up to 200 chats once and group by namespace. Reasonable single-
  // user cap for v1; a dedicated aggregate endpoint is a future patch.
  const chats = useChatList({ limit: 200, offset: 0 })

  const [tab, setTab] = useState<TabKey>('all')
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  // ── Build combined namespace list ────────────────────────────────
  const combined = useMemo<CombinedNamespace[]>(() => {
    const byName = new Map<string, CombinedNamespace>()
    for (const ns of memNs.data ?? []) {
      byName.set(ns.namespace, {
        namespace: ns.namespace,
        memory_count: ns.count,
        chat_count: 0,
        description: ns.description,
        consolidated_summary: ns.consolidated_summary,
        consolidated_summary_tier: ns.consolidated_summary_tier,
        consolidated_summary_updated_at: ns.consolidated_summary_updated_at,
        related_namespaces: ns.related_namespaces,
      })
    }
    for (const chat of chats.data?.items ?? []) {
      const entry = byName.get(chat.namespace) ?? {
        namespace: chat.namespace,
        memory_count: 0,
        chat_count: 0,
      }
      entry.chat_count += 1
      byName.set(chat.namespace, entry)
    }
    // Sort: rows with most total content first; ties broken alphabetically.
    return [...byName.values()].sort((a, b) => {
      const totalA = a.memory_count + a.chat_count
      const totalB = b.memory_count + b.chat_count
      if (totalA !== totalB) return totalB - totalA
      return a.namespace.localeCompare(b.namespace)
    })
  }, [memNs.data, chats.data])

  // Per-tab counts for the trigger badges (computed pre-search so the
  // user always sees the global tab totals).
  const tabCounts = useMemo(
    () => ({
      all: combined.length,
      memories: combined.filter((n) => n.memory_count > 0).length,
      chats: combined.filter((n) => n.chat_count > 0).length,
    }),
    [combined],
  )

  // Filter rows by active tab + search query.
  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return combined.filter((n) => {
      if (tab === 'memories' && n.memory_count === 0) return false
      if (tab === 'chats' && n.chat_count === 0) return false
      if (needle && !n.namespace.toLowerCase().includes(needle)) return false
      return true
    })
  }, [combined, tab, search])

  const isLoading = memNs.isLoading || chats.isLoading
  const error = memNs.error ?? chats.error

  return (
    <PageShell>
      <div className="mx-auto max-w-[960px] px-6 py-8">
        <header className="mb-6">
          <h1 className="flex items-center gap-2 text-[22px] font-semibold text-content-primary">
            <FolderTree size={20} /> Namespaces
          </h1>
          <p className="mt-1 text-[13px] text-content-secondary">
            Cross-session rollups for every namespace in the vault. Use the
            tabs to scope by content type and the search to find a namespace
            by name.
          </p>
        </header>

        <Tabs.Root
          value={tab}
          onValueChange={(v) => setTab(v as TabKey)}
          className="mb-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Tabs.List className="inline-flex items-center gap-1 rounded-lg bg-black/[0.04] p-1">
              <TabTrigger value="all" label="All" count={tabCounts.all} />
              <TabTrigger value="memories" label="Memories" count={tabCounts.memories} />
              <TabTrigger value="chats" label="Chats" count={tabCounts.chats} />
            </Tabs.List>
            <div className="relative w-full max-w-[280px]">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
              />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search namespaces…"
                aria-label="Search namespaces"
                className="w-full rounded-lg border border-border bg-white py-2 pl-9 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
              />
            </div>
          </div>
        </Tabs.Root>

        {isLoading && <LoadingSkeleton />}
        {error && (
          <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
            Failed to load namespaces: {String((error as Error).message || error)}
          </div>
        )}

        {!isLoading && filtered.length === 0 && combined.length === 0 && (
          <div className="rounded-lg border border-dashed border-black/[0.08] bg-white p-12 text-center">
            <FolderTree size={28} className="mx-auto text-content-tertiary" />
            <div className="mt-3 text-sm font-medium text-content-primary">
              No namespaces yet
            </div>
            <div className="mt-1 text-[12px] text-content-tertiary">
              Namespaces appear here as soon as an agent stores its first
              memory — or the Chrome Extension pushes its first chat.
            </div>
          </div>
        )}

        {!isLoading && filtered.length === 0 && combined.length > 0 && (
          <div className="rounded-lg border border-dashed border-black/[0.08] bg-white p-10 text-center">
            <Search size={22} className="mx-auto text-content-tertiary" />
            <div className="mt-2 text-sm font-medium text-content-primary">
              No matches
            </div>
            <div className="mt-1 text-[12px] text-content-tertiary">
              {search.trim()
                ? `No namespaces match "${search.trim()}" in this tab.`
                : `No namespaces in the "${tab}" tab.`}
            </div>
          </div>
        )}

        {filtered.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-black/[0.06] bg-white shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
            {filtered.map((ns) => (
              <NamespaceRow
                key={ns.namespace}
                ns={ns}
                expanded={expanded === ns.namespace}
                onToggle={() =>
                  setExpanded((prev) => (prev === ns.namespace ? null : ns.namespace))
                }
                activeTab={tab}
              />
            ))}
          </div>
        )}
      </div>
    </PageShell>
  )
}
