/**
 * Kemory — Namespaces Page
 *
 * First-class surface for namespace management:
 *   - One row per namespace
 *   - Description + cross-session consolidated summary (L3.1 with L3.0 fallback)
 *   - Related-namespace badge that expands to show near-duplicates the
 *     matcher auto-redirected or suggested at create time
 *   - Click a row → inline detail drawer with the full summary and a
 *     link to the Memory Explorer filtered to that namespace
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FolderTree, Sparkles, Link2, ChevronRight } from 'lucide-react'
import { PageShell } from '@/components/layout/PageShell'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { useNamespaces, useNamespaceSummary } from '@/hooks/useMemories'
import type { NamespaceInfo } from '@/api/types'
import { formatRelativeTime, cn } from '@/lib/utils'

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

function NamespaceDetailDrawer({ namespace, count }: { namespace: string; count: number }) {
  const { data, isLoading } = useNamespaceSummary(namespace)
  if (isLoading) {
    return <div className="py-6"><LoadingSkeleton /></div>
  }
  if (!data) {
    return <div className="py-6 text-sm text-content-tertiary">No summary available.</div>
  }
  return (
    <div className="space-y-4 px-6 py-5">
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
          Description
        </div>
        <div className="mt-1 text-sm text-content-primary whitespace-pre-wrap">
          {data.description || <span className="text-content-tertiary">(none)</span>}
        </div>
      </div>

      <div>
        <div className="flex items-center gap-2">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
            Consolidated summary
          </div>
          <TierBadge tier={data.consolidated_summary_tier} />
          {data.consolidated_summary_updated_at ? (
            <span className="text-[11px] text-content-tertiary">
              updated {formatRelativeTime(data.consolidated_summary_updated_at)}
            </span>
          ) : null}
        </div>
        <div className="mt-1 whitespace-pre-wrap rounded-md bg-black/[0.02] p-3 text-sm text-content-primary ring-1 ring-black/[0.04]">
          {data.consolidated_summary || (
            <span className="text-content-tertiary">
              {count < 2
                ? `Not yet consolidated. Needs ≥2 memories for L3 summary (have ${count}).`
                : count < 3
                  ? 'Pending — L3 narrative summary has not yet run for this namespace. It should appear shortly after the next write.'
                  : 'Pending — the compression pipeline has not produced a summary yet despite sufficient memories. The background job may not have run; try creating a new memory or running the backfill script.'}
            </span>
          )}
        </div>
      </div>

      {data.related_namespaces.length > 0 && (
        <div>
          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
            <Link2 size={12} /> Related namespaces (auto-detected)
          </div>
          <ul className="mt-2 space-y-1">
            {data.related_namespaces.map((r, idx) => (
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

      <Link
        to={`/memories?namespace=${encodeURIComponent(namespace)}`}
        className="inline-flex items-center gap-1 text-[12px] font-medium text-indigo-600 hover:text-indigo-700"
      >
        Open in Memory Explorer <ChevronRight size={14} />
      </Link>
    </div>
  )
}

function NamespaceRow({
  ns,
  expanded,
  onToggle,
}: {
  ns: NamespaceInfo
  expanded: boolean
  onToggle: () => void
}) {
  const relatedCount = ns.related_namespaces?.length ?? 0
  const summaryPreview = (ns.consolidated_summary || '').slice(0, 180)
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
          <div className="flex items-center gap-2">
            <FolderTree size={14} className="text-content-tertiary shrink-0" />
            <div className="truncate font-mono text-[13px] font-semibold text-content-primary">
              {ns.namespace}
            </div>
            <TierBadge tier={ns.consolidated_summary_tier} />
            {relatedCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-amber-200">
                <Link2 size={10} /> {relatedCount} related
              </span>
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
        <div className="text-right">
          <div className="font-mono text-[13px] font-semibold text-content-primary">
            {ns.count.toLocaleString()}
          </div>
          <div className="text-[10px] uppercase tracking-wider text-content-tertiary">memories</div>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-black/[0.04] bg-black/[0.015]">
          <NamespaceDetailDrawer namespace={ns.namespace} count={ns.count} />
        </div>
      )}
    </div>
  )
}

export function NamespacesPage() {
  const { data, isLoading, error } = useNamespaces()
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <PageShell>
      <div className="mx-auto max-w-[960px] px-6 py-8">
        <header className="mb-6">
          <h1 className="flex items-center gap-2 text-[22px] font-semibold text-content-primary">
            <FolderTree size={20} /> Namespaces
          </h1>
          <p className="mt-1 text-[13px] text-content-secondary">
            Cross-session rollups (L3.1, L3.0 fallback) and duplicate-detection
            results for every namespace in the vault.
          </p>
        </header>

        {isLoading && <LoadingSkeleton />}
        {error && (
          <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
            Failed to load namespaces: {String((error as Error).message || error)}
          </div>
        )}

        {data && data.length === 0 && (
          <div className="rounded-lg border border-dashed border-black/[0.08] bg-white p-12 text-center">
            <FolderTree size={28} className="mx-auto text-content-tertiary" />
            <div className="mt-3 text-sm font-medium text-content-primary">
              No namespaces yet
            </div>
            <div className="mt-1 text-[12px] text-content-tertiary">
              Namespaces appear here as soon as an agent stores its first memory.
            </div>
          </div>
        )}

        {data && data.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-black/[0.06] bg-white shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
            {data.map((ns) => (
              <NamespaceRow
                key={ns.namespace}
                ns={ns}
                expanded={expanded === ns.namespace}
                onToggle={() =>
                  setExpanded((prev) => (prev === ns.namespace ? null : ns.namespace))
                }
              />
            ))}
          </div>
        )}
      </div>
    </PageShell>
  )
}
