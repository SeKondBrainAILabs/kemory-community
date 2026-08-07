import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { ArrowUpDown } from 'lucide-react'

interface DataTableProps<T> {
  columns: ColumnDef<T, unknown>[]
  data: T[]
  onRowClick?: (row: T) => void
  initialSorting?: SortingState
  stickyHeader?: boolean
  maxHeight?: string
}

export function DataTable<T>({
  columns,
  data,
  onRowClick,
  initialSorting,
  stickyHeader = false,
  maxHeight,
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting ?? [])

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  return (
    <div
      className={cn(
        'rounded-lg border border-border bg-white',
        maxHeight ? 'overflow-auto' : 'overflow-hidden',
      )}
      style={maxHeight ? { maxHeight } : undefined}
    >
      <table className="w-full text-sm">
        <thead className={cn(stickyHeader && 'sticky top-0 z-10')}>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="bg-surface-secondary">
              {hg.headers.map((header) => (
                <th
                  key={header.id}
                  className={cn(
                    'bg-surface-secondary px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-content-secondary',
                    header.column.getCanSort() && 'cursor-pointer select-none',
                  )}
                  onClick={header.column.getToggleSortingHandler()}
                >
                  <div className="flex items-center gap-1">
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {header.column.getCanSort() && <ArrowUpDown size={14} />}
                  </div>
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              onClick={() => onRowClick?.(row.original)}
              // S9N-6164: keyboard-activatable rows so the detail panel can be
              // opened without a mouse (Enter/Space), satisfying the a11y gate.
              {...(onRowClick && {
                tabIndex: 0,
                role: 'button',
                onKeyDown: (e: React.KeyboardEvent) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onRowClick(row.original)
                  }
                },
              })}
              className={cn(
                'border-t border-border transition-colors hover:bg-surface-secondary',
                onRowClick &&
                  'cursor-pointer focus:outline-none focus-visible:bg-surface-secondary focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-primary',
              )}
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-4 py-3 text-content-primary">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
          {table.getRowModel().rows.length === 0 && (
            <tr>
              <td
                colSpan={columns.length}
                className="px-4 py-8 text-center text-content-tertiary"
              >
                No data
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
