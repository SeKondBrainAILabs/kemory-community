import type { LucideIcon } from 'lucide-react'
import { SearchX } from 'lucide-react'

interface EmptyStateProps {
  /** Icon shown above the title. Defaults to a "no search results" glyph. */
  icon?: LucideIcon
  title: string
  description?: string
  /** Optional primary action, e.g. "Clear search". */
  action?: { label: string; onClick: () => void }
}

/**
 * S9N-6163: shared empty state — reused by search/filter zero-result views
 * across every page epic. Replaces the ambiguous bare "No data" text.
 */
export function EmptyState({ icon: Icon = SearchX, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-border bg-white px-6 py-16 text-center">
      <Icon size={32} className="mb-3 text-content-tertiary" aria-hidden />
      <p className="text-sm font-medium text-content-primary">{title}</p>
      {description && <p className="mt-1 max-w-sm text-xs text-content-secondary">{description}</p>}
      {action && (
        <button
          onClick={action.onClick}
          className="mt-4 rounded-lg border border-border bg-white px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary focus-visible:outline-brand-primary"
        >
          {action.label}
        </button>
      )}
    </div>
  )
}
