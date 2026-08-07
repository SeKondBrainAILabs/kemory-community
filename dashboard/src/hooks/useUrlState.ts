import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

export function useUrlState() {
  const [params, setParams] = useSearchParams()

  const get = useCallback(
    (key: string, defaultValue = '') => params.get(key) ?? defaultValue,
    [params],
  )

  const set = useCallback(
    (changes: Record<string, string | null>) => {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous)
          for (const [key, value] of Object.entries(changes)) {
            if (value === null) next.delete(key)
            else next.set(key, value)
          }
          return next
        },
        { replace: true },
      )
    },
    [setParams],
  )

  return { get, set }
}
