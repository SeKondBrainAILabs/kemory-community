import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

export function getPageList(current: number, count: number): (number | 'gap')[] {
  if (count <= 7) return Array.from({ length: count }, (_, index) => index + 1)
  const pages: (number | 'gap')[] = [1]
  const low = Math.max(2, current - 1)
  const high = Math.min(count - 1, current + 1)
  if (low > 2) pages.push('gap')
  for (let page = low; page <= high; page += 1) pages.push(page)
  if (high < count - 1) pages.push('gap')
  pages.push(count)
  return pages
}

interface PaginationProps {
  page: number
  pageCount: number
  pageSize: number
  total: number
  label?: string
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
  sizeOptions?: number[]
}

export function Pagination({
  page,
  pageCount,
  pageSize,
  total,
  label = 'items',
  onPageChange,
  onPageSizeChange,
  sizeOptions = [25, 50, 100],
}: PaginationProps) {
  const current = page + 1

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-white px-3 py-2 text-xs text-content-secondary">
      <div className="flex items-center gap-2">
        <span>
          {total.toLocaleString()} {total === 1 ? label.replace(/s$/, '') : label}
        </span>
        <select
          value={pageSize}
          onChange={(event) => onPageSizeChange(Number(event.target.value))}
          aria-label="Rows per page"
          className="rounded-md border border-border bg-white px-1.5 py-1 text-xs focus:border-brand-primary focus:outline-none"
        >
          {sizeOptions.map((size) => (
            <option key={size} value={size}>
              {size} / page
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page === 0}
          aria-label="Previous page"
          className="rounded p-1 hover:bg-surface-secondary disabled:opacity-40"
        >
          <ChevronLeft size={14} />
        </button>
        {getPageList(current, pageCount).map((item, index) =>
          item === 'gap' ? (
            <span key={`gap-${index}`} className="px-1 text-content-tertiary" aria-hidden="true">
              ...
            </span>
          ) : (
            <button
              key={item}
              type="button"
              onClick={() => onPageChange(item - 1)}
              aria-label={`Page ${item}`}
              aria-current={item === current ? 'page' : undefined}
              className={cn(
                'min-w-[1.75rem] rounded px-1.5 py-1 text-center font-medium',
                item === current
                  ? 'bg-brand-primaryDark text-white'
                  : 'text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {item}
            </button>
          ),
        )}
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pageCount - 1}
          aria-label="Next page"
          className="rounded p-1 hover:bg-surface-secondary disabled:opacity-40"
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  )
}
