import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronsUpDown, Search } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { NamespaceInfo } from '@/api/types'

interface NamespaceComboboxProps {
  namespaces: NamespaceInfo[]
  value: string
  totalCount: number
  onChange: (namespace: string) => void
}

export function NamespaceCombobox({
  namespaces,
  value,
  totalCount,
  onChange,
}: NamespaceComboboxProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listId = 'memory-namespace-options'

  const options = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    const matches = namespaces.filter((item) => item.namespace.toLowerCase().includes(normalized))
    return normalized === '' || 'all namespaces'.includes(normalized)
      ? [{ namespace: '', count: totalCount }, ...matches]
      : matches
  }, [namespaces, query, totalCount])

  useEffect(() => setActiveIndex(0), [query, open])

  useEffect(() => {
    if (!open) return
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', closeOnOutsideClick)
    return () => document.removeEventListener('mousedown', closeOnOutsideClick)
  }, [open])

  function choose(namespace: string) {
    onChange(namespace)
    setOpen(false)
    setQuery('')
  }

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((index) => Math.min(options.length - 1, index + 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((index) => Math.max(0, index - 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const option = options[activeIndex]
      if (option) choose(option.namespace)
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  const selectedCount = value
    ? (namespaces.find((item) => item.namespace === value)?.count ?? 0)
    : totalCount
  const selectedLabel = value || 'All namespaces'

  return (
    <div ref={rootRef} className="relative w-full sm:w-72">
      <button
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => {
          setOpen((current) => !current)
          window.setTimeout(() => inputRef.current?.focus(), 0)
        }}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-border bg-white px-3 py-2 text-left text-sm text-content-primary focus:border-brand-primary focus:outline-none"
      >
        <span className="truncate">
          {selectedLabel} · {selectedCount.toLocaleString()}
        </span>
        <ChevronsUpDown size={14} className="shrink-0 text-content-tertiary" />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full min-w-[16rem] overflow-hidden rounded-lg border border-border bg-white shadow-lg">
          <div className="flex items-center gap-2 border-b border-border px-2.5 py-1.5">
            <Search size={14} className="text-content-tertiary" />
            <input
              ref={inputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search namespaces..."
              aria-label="Search namespaces"
              aria-controls={listId}
              aria-activedescendant={options[activeIndex] ? `namespace-option-${activeIndex}` : undefined}
              className="w-full bg-transparent text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none"
            />
          </div>
          <ul id={listId} role="listbox" className="max-h-72 overflow-y-auto py-1">
            {options.length === 0 && (
              <li className="px-3 py-2 text-xs text-content-tertiary">No namespaces match.</li>
            )}
            {options.map((option, index) => {
              const selected = option.namespace === value
              return (
                <li
                  key={option.namespace || '__all__'}
                  id={`namespace-option-${index}`}
                  role="option"
                  aria-selected={selected}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => choose(option.namespace)}
                  className={cn(
                    'flex cursor-pointer items-center justify-between gap-2 px-3 py-1.5 text-sm',
                    index === activeIndex && 'bg-surface-secondary',
                  )}
                >
                  <span className="flex min-w-0 items-center gap-1.5">
                    <Check
                      size={13}
                      className={cn('shrink-0', selected ? 'text-brand-primaryDark' : 'text-transparent')}
                    />
                    <span className="truncate text-content-primary">
                      {option.namespace || 'All namespaces'}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs text-content-tertiary">{option.count}</span>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
